#!/usr/bin/env python3
"""
GitHub Actions Host-Based Runner Deployment Script
===================================================
Idempotent deployment of self-hosted GitHub Actions runners directly on the host.

Reads config.yml and:
1. Validates configuration
2. Installs runner binaries on host
3. Creates systemd service files
4. Registers runners with GitHub
5. Starts/enables systemd services
"""

import os
import sys
import subprocess
import json
import shlex
import shutil
import argparse
import time
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)


# Global flags for logging behavior
VERBOSE = False
DRY_RUN = False


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'


def log(msg: str, level: str = "info", newline: bool = True):
    """Colored logging with consistent formatting"""
    colors = {
        "info": Colors.OKBLUE,
        "success": Colors.OKGREEN,
        "warning": Colors.WARNING,
        "error": Colors.FAIL,
        "header": Colors.BOLD + Colors.HEADER,
        "debug": Colors.DIM,
    }
    color = colors.get(level, "")
    prefix = level.upper()

    # Format prefix for alignment
    if level == "debug" and not VERBOSE:
        return  # Skip debug logs unless verbose mode

    end_char = '\n' if newline else ''
    print(f"{color}[{prefix:7}]{Colors.ENDC} {msg}", end=end_char)


def log_debug(msg: str):
    """Debug logging (only shown in verbose mode)"""
    if VERBOSE:
        log(msg, "debug")


def log_dry_run(action: str, details: str = ""):
    """Log dry-run actions"""
    if DRY_RUN:
        msg = f"[DRY-RUN] {action}"
        if details:
            msg += f": {details}"
        log(msg, "info")


def run_cmd(
    cmd: List[str],
    check: bool = True,
    capture: bool = False,
    sudo: bool = False,
    dry_run_msg: Optional[str] = None,
    sudo_reason: Optional[str] = None
) -> Optional[subprocess.CompletedProcess]:
    """
    Run shell command with error handling, dry-run support, and verbose logging

    Args:
        cmd: Command and arguments as list
        check: Raise exception on non-zero exit
        capture: Capture stdout/stderr
        sudo: Prepend sudo if not running as root
        dry_run_msg: Custom message for dry-run mode
        sudo_reason: Explanation for why sudo is needed (shown before password prompt)

    Returns:
        CompletedProcess or None (in dry-run mode)
    """
    need_sudo = sudo and os.geteuid() != 0

    if need_sudo:
        # Show clear message about why sudo is needed
        reason = sudo_reason or dry_run_msg or "system operation"
        log(f"🔒 Requesting sudo access for: {reason}", "info")
        cmd = ["sudo"] + cmd

    # Log command in verbose mode
    cmd_str = ' '.join(shlex.quote(arg) for arg in cmd)
    log_debug(f"Command: {cmd_str}")

    # Handle dry-run mode
    if DRY_RUN:
        msg = dry_run_msg or f"Would run: {cmd_str}"
        log_dry_run(msg)
        # Return mock result for dry-run
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    # Execute command
    start_time = time.time()
    try:
        if capture:
            result = subprocess.run(cmd, check=check, capture_output=True, text=True)
        else:
            result = subprocess.run(cmd, check=check)

        elapsed = time.time() - start_time
        log_debug(f"Command completed in {elapsed:.2f}s")

        if capture and VERBOSE and result.stdout:
            log_debug(f"Output: {result.stdout.strip()}")

        return result

    except subprocess.CalledProcessError as e:
        elapsed = time.time() - start_time
        log(f"Command failed after {elapsed:.2f}s: {cmd_str}", "error")
        if hasattr(e, 'stderr') and e.stderr:
            log(f"STDERR: {e.stderr}", "error")
        if hasattr(e, 'stdout') and e.stdout:
            log(f"STDOUT: {e.stdout}", "error")
        raise


def check_requirements():
    """Verify required tools are installed"""
    log("Checking requirements...", "info")
    required = ["git", "curl", "systemctl"]

    for tool in required:
        if not shutil.which(tool):
            log(f"Missing required tool: {tool}", "error")
            sys.exit(1)

    log("Requirements OK", "success")


class RunnerConfig:
    """Parsed runner configuration"""

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.parsed = self._parse_name()
        self._validate()

    def _parse_name(self) -> Dict[str, Any]:
        """
        Parse runner name: {type}-{size}-[{category}]-{number}
        - type = 'cpu' | 'gpu'
        - size = 'xs' | 'small' | 'medium' | 'large' | 'max'
        - category = optional specialization (e.g., 'docker', 'bazel')
        - number = 1, 2, 3, ...

        Examples:
        - cpu-medium-1 → Generic CPU runner
        - cpu-medium-docker-1 → CPU runner for Docker builds
        - gpu-large-cuda-1 → GPU runner for CUDA workloads
        """
        parts = self.name.split('-')
        if len(parts) not in [3, 4]:
            raise ValueError(
                f"Invalid runner name '{self.name}'. "
                f"Expected format: {{type}}-{{size}}-[{{category}}]-{{number}}"
            )

        # Parse based on number of parts
        if len(parts) == 3:
            runner_type, size, number = parts
            category = None
        else:  # len(parts) == 4
            runner_type, size, category, number = parts

        # Validate number
        try:
            int(number)
        except ValueError:
            raise ValueError(f"Invalid number in runner name '{self.name}': '{number}'")

        # Only allow 'cpu' or 'gpu'
        if runner_type not in ['cpu', 'gpu']:
            raise ValueError(
                f"Invalid runner type '{runner_type}' in runner name '{self.name}'. "
                f"Only 'cpu' and 'gpu' are allowed as runner types."
            )

        return {
            'size': size,
            'number': number,
            'category': category,
            'gpu': runner_type == 'gpu',
            'type': runner_type,
        }

    def _validate(self):
        """Validate parsed configuration"""
        # Check size exists in config
        if self.parsed['size'] not in self.config['sizes']:
            raise ValueError(
                f"Unknown size '{self.parsed['size']}' in runner '{self.name}'. "
                f"Available: {list(self.config['sizes'].keys())}"
            )

        # Only allow cpu or gpu types
        if self.parsed['type'] not in ['cpu', 'gpu']:
            raise ValueError(
                f"Invalid type '{self.parsed['type']}' in runner '{self.name}'. "
                f"Only 'cpu' and 'gpu' are allowed. Use containers for custom environments."
            )

    @property
    def service_name(self) -> str:
        """Systemd service name"""
        prefix = self.config['github']['prefix']
        return f"gha-{prefix}-linux-{self.name}"

    @property
    def registered_name(self) -> str:
        """GitHub registered runner name"""
        prefix = self.config['github']['prefix']
        return f"{prefix}-linux-{self.name}"

    @property
    def labels(self) -> str:
        """Comma-separated labels for GitHub"""
        parts = [
            "self-hosted",
            "linux",
            self.config['host']['label'],
        ]

        # Add type (cpu or gpu)
        parts.append(self.parsed['type'])

        # Add size
        parts.append(self.parsed['size'])

        # Add category (generic if none specified)
        if self.parsed['category']:
            parts.append(self.parsed['category'])
        else:
            parts.append('generic')

        return ','.join(parts)

    @property
    def runner_path(self) -> str:
        """Host runner directory path"""
        base = self.config['host']['runner_base']
        return f"{base}/{self.registered_name}"

    @property
    def size_config(self) -> Dict[str, Any]:
        """Resource limits for this runner"""
        return self.config['sizes'][self.parsed['size']]


class HostDeployer:
    """Main deployment orchestrator for host-based runners"""

    def __init__(self, config_path: str = "config.yml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.runners = self._parse_runners()
        self.git_sha = self._get_git_sha()
        self.version_tag = self._get_version_tag()

    def _load_config(self) -> Dict[str, Any]:
        """Load and validate config.yml"""
        if not self.config_path.exists():
            log(f"Config file not found: {self.config_path}", "error")
            sys.exit(1)

        with open(self.config_path) as f:
            config = yaml.safe_load(f)

        # Validate required sections
        required = ['github', 'host', 'runners', 'sizes', 'runner']
        for section in required:
            if section not in config:
                log(f"Missing required section in config: {section}", "error")
                sys.exit(1)

        # Apply defaults for optional sections
        config.setdefault('cache', {})
        config['cache'].setdefault('base_dir', '/srv/gha-cache')
        config['cache'].setdefault('permissions', '755')

        config.setdefault('systemd', {})
        config['systemd'].setdefault('restart_policy', 'always')
        config['systemd'].setdefault('restart_sec', 10)

        config.setdefault('sudoers', {})
        config['sudoers'].setdefault('path', '/etc/sudoers.d/gha-runner-cleanup')

        return config

    def _parse_runners(self) -> List[RunnerConfig]:
        """Parse all runner configurations"""
        runners = []
        for name in self.config['runners']:
            try:
                runner = RunnerConfig(name, self.config)
                runners.append(runner)
            except ValueError as e:
                log(str(e), "error")
                sys.exit(1)

        return runners

    def validate_config(self) -> bool:
        """Validate configuration without deploying"""
        log("Validating configuration...", "header")
        errors = []
        warnings = []

        # Check for placeholder values
        org = self.config.get('github', {}).get('org', '')
        if org in ['your-org', '', None]:
            errors.append("GitHub organization not set in config.yml (still using placeholder 'your-org')")

        prefix = self.config.get('github', {}).get('prefix', '')
        if not prefix or prefix == '':
            errors.append("GitHub prefix not set in config.yml")

        # Check host configuration
        host_config = self.config.get('host', {})
        if not host_config.get('runner_base'):
            errors.append("Host runner_base not configured")
        if not host_config.get('label'):
            errors.append("Host label not configured")
        if not host_config.get('docker_user_uid'):
            errors.append("Host docker_user_uid not configured")
        if not host_config.get('docker_user_gid'):
            errors.append("Host docker_user_gid not configured")

        # Check runner configuration
        runner_config = self.config.get('runner', {})
        if not runner_config.get('version'):
            errors.append("Runner version not configured")
        if not runner_config.get('arch'):
            errors.append("Runner architecture not configured")

        # Validate runners list
        if not self.config.get('runners'):
            errors.append("No runners defined in config.yml")
        elif len(self.config['runners']) == 0:
            warnings.append("Runners list is empty - nothing to deploy")

        # Validate runner names and sizes
        for runner_name in self.config.get('runners', []):
            try:
                runner = RunnerConfig(runner_name, self.config)
                # Check if size is defined
                if runner.parsed['size'] not in self.config.get('sizes', {}):
                    errors.append(f"Runner '{runner_name}' uses undefined size '{runner.parsed['size']}'")
            except ValueError as e:
                errors.append(f"Invalid runner name '{runner_name}': {e}")

        # Validate sizes
        if not self.config.get('sizes'):
            errors.append("No sizes defined in config.yml")
        else:
            for size_name, size_config in self.config['sizes'].items():
                if size_name not in ['xs', 'small', 'medium', 'large', 'max']:
                    warnings.append(f"Non-standard size name '{size_name}' - expected: xs, small, medium, large, max")

                # Validate size config structure
                if not isinstance(size_config, dict):
                    errors.append(f"Size '{size_name}' configuration must be a dictionary")
                    continue

                # Check for cpus, mem_limit, pids_limit (optional but recommended)
                if 'cpus' not in size_config and size_name != 'max':
                    warnings.append(f"Size '{size_name}' missing 'cpus' limit (recommended)")
                if 'mem_limit' not in size_config and size_name != 'max':
                    warnings.append(f"Size '{size_name}' missing 'mem_limit' (recommended)")
                if 'pids_limit' not in size_config and size_name != 'max':
                    warnings.append(f"Size '{size_name}' missing 'pids_limit' (recommended)")

        # Check for duplicate runner names
        runner_names = self.config.get('runners', [])
        if len(runner_names) != len(set(runner_names)):
            duplicates = [name for name in runner_names if runner_names.count(name) > 1]
            errors.append(f"Duplicate runner names found: {set(duplicates)}")

        # Print results
        if errors:
            log("\n❌ Validation FAILED - Configuration has errors:", "error")
            for error in errors:
                log(f"  • {error}", "error")

        if warnings:
            log("\n⚠️  Warnings:", "warning")
            for warning in warnings:
                log(f"  • {warning}", "warning")

        if not errors and not warnings:
            log("\n✅ Configuration is valid!", "success")
            log(f"  • Organization: {org}", "info")
            log(f"  • Prefix: {prefix}", "info")
            log(f"  • Runners: {len(runner_names)}", "info")
            log(f"  • Sizes: {len(self.config.get('sizes', {}))}", "info")
            return True
        elif not errors:
            log("\n✅ Configuration is valid (with warnings)", "success")
            return True
        else:
            log("\nPlease fix the errors above and try again.", "error")
            return False

    def _get_git_sha(self) -> str:
        """Get current git commit SHA"""
        try:
            result = run_cmd(["git", "rev-parse", "--short", "HEAD"], capture=True)
            return result.stdout.strip()
        except Exception:
            return "no-git"

    def _get_version_tag(self) -> str:
        """Generate version tag: YYYY.MM.DD-sha"""
        date = datetime.now(timezone.utc).strftime("%Y.%m.%d")
        return f"{date}-{self.git_sha}"

    def fetch_github_token(self):
        """Fetch a fresh registration token from GitHub"""
        # Run gh as the original user (not root) to access their gh auth
        sudo_user = os.environ.get('SUDO_USER')
        gh_prefix = []
        if sudo_user and os.geteuid() == 0:
            gh_prefix = ["sudo", "-u", sudo_user]

        org = self.config['github']['org']

        try:
            log(f"Fetching registration token for org: {org}...", "info")
            cmd = gh_prefix + ["gh", "api", "-X", "POST", f"/orgs/{org}/actions/runners/registration-token", "--jq", ".token"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            token = result.stdout.strip()

            if not token:
                log("Failed to fetch token: empty response", "error")
                return None

            return token

        except subprocess.CalledProcessError as e:
            log(f"Failed to fetch registration token", "error")
            if e.stderr:
                log(f"Error: {e.stderr.strip()}", "error")
            log("Possible causes:", "error")
            log("  • Not authenticated with gh CLI (run 'gh auth login')", "error")
            log("  • Insufficient permissions for the organization", "error")
            log("  • Organization name incorrect in config.yml", "error")
            return None
        except Exception as e:
            log(f"Unexpected error fetching token: {e}", "error")
            return None

    def ensure_github_token(self):
        """Check for registration token and fetch if needed"""
        token = os.environ.get("REGISTER_GITHUB_RUNNER_TOKEN")

        if token:
            log("Registration token found in environment", "info")
            # Basic sanity check on format
            if len(token) < 20 or not token.isprintable():
                log("Token format looks invalid, fetching fresh token...", "warning")
                token = None
            else:
                log("Using provided token (will be validated during runner registration)", "success")
                return True

        if not token:
            log("Fetching fresh registration token...", "warning")

            # Check if gh CLI is available
            if not shutil.which("gh"):
                log("GitHub CLI (gh) not found. Cannot fetch token automatically.", "error")
                log("Install gh CLI or manually set REGISTER_GITHUB_RUNNER_TOKEN", "error")
                return False

            # Fetch fresh token
            token = self.fetch_github_token()
            if not token:
                return False

            # Set the token in the environment for this process
            os.environ["REGISTER_GITHUB_RUNNER_TOKEN"] = token
            log("Registration token fetched successfully", "success")
            return True

        return True

    def ensure_directories(self):
        """Create runner directories with proper ownership"""
        log("Ensuring runner directories exist...", "info")

        base = self.config['host']['runner_base']
        base_path = Path(base)
        uid = self.config['host']['docker_user_uid']
        gid = self.config['host']['docker_user_gid']

        log_debug(f"Base directory: {base_path}")
        log_debug(f"Owner UID:GID: {uid}:{gid}")

        # Ensure base directory exists
        if not base_path.exists() or DRY_RUN:
            log(f"Creating {base}...", "info")
            run_cmd(
                ["mkdir", "-p", str(base_path)],
                sudo=True,
                sudo_reason=f"creating runner base directory {base_path}",
                dry_run_msg=f"Create base directory {base_path}"
            )

        # Create individual runner directories
        for runner in self.runners:
            path = Path(runner.runner_path)
            if not path.exists() or DRY_RUN:
                log(f"Creating {path}...", "info")
                run_cmd(
                    ["mkdir", "-p", str(path)],
                    sudo=True,
                    sudo_reason=f"creating runner directory {path}",
                    dry_run_msg=f"Create runner directory {path}"
                )

        # Set ownership
        log(f"Setting ownership {uid}:{gid} on {base}...", "info")
        run_cmd(
            ["chown", "-R", f"{uid}:{gid}", str(base_path)],
            sudo=True,
            sudo_reason=f"setting ownership on {base_path}",
            dry_run_msg=f"Set ownership {uid}:{gid} on {base_path}"
        )

        # Create shared cache directory for corca-ai/local-cache
        # Used as a general cache across ecosystems (e.g. Poetry, npm, Cargo)
        cache_dir = Path(self.config['cache']['base_dir'])
        if not cache_dir.exists() or DRY_RUN:
            log(f"Creating shared cache directory {cache_dir}...", "info")
            run_cmd(
                ["mkdir", "-p", str(cache_dir)],
                sudo=True,
                sudo_reason=f"creating shared cache directory {cache_dir}",
                dry_run_msg=f"Create cache directory {cache_dir}"
            )
        # Always ensure correct ownership/permissions (fix if directory exists with wrong perms)
        run_cmd(
            ["chown", f"{uid}:{gid}", str(cache_dir)],
            sudo=True,
            sudo_reason=f"setting cache directory ownership",
            dry_run_msg=f"Set cache directory ownership {uid}:{gid}"
        )
        cache_perms = self.config['cache']['permissions']
        run_cmd(
            ["chmod", cache_perms, str(cache_dir)],
            sudo=True,
            sudo_reason=f"setting cache directory permissions",
            dry_run_msg=f"Set cache directory permissions {cache_perms}"
        )
        log("Shared cache directory ready", "success")

        log("Directories ready", "success")

    def install_dependencies(self, runner: RunnerConfig):
        """No dependencies needed - everything runs in containers!"""
        # Generic runners (cpu/gpu) don't need any host dependencies
        # All dependencies should be in container images
        log(f"No host dependencies for {runner.parsed['type']} runner (use containers!)", "info")
        return

    def install_runner_binary(self, runner: RunnerConfig):
        """Download and extract GitHub Actions runner binary"""
        runner_path = Path(runner.runner_path)
        config_script = runner_path / "config.sh"

        # Check if runner is already installed
        if config_script.exists() and not DRY_RUN:
            log(f"Runner binary already installed at {runner_path}", "info")
            log_debug(f"Config script found: {config_script}")
            return

        log(f"Installing runner binary for {runner.registered_name}...", "info")

        version = self.config['runner']['version']
        arch = self.config['runner']['arch']

        # Use custom download URL template if provided, otherwise use default GitHub releases
        url_template = self.config['runner'].get(
            'download_url_template',
            'https://github.com/actions/runner/releases/download/v{version}/actions-runner-{arch}-{version}.tar.gz'
        )
        tarball_url = url_template.format(version=version, arch=arch)
        tarball_path = runner_path / "runner.tar.gz"

        log_debug(f"Runner version: {version}")
        log_debug(f"Architecture: {arch}")
        log_debug(f"Download URL: {tarball_url}")

        # Download runner tarball
        log(f"Downloading runner v{version}...", "info")
        run_cmd(
            ["curl", "-fsSL", "-o", str(tarball_path), tarball_url],
            dry_run_msg=f"Download runner v{version} from GitHub"
        )

        # Extract tarball
        log("Extracting runner...", "info")
        run_cmd(
            ["tar", "xzf", str(tarball_path), "-C", str(runner_path)],
            dry_run_msg=f"Extract runner to {runner_path}"
        )

        # Remove tarball
        if not DRY_RUN:
            tarball_path.unlink()
        else:
            log_dry_run(f"Remove tarball {tarball_path}")

        # Fix ownership
        uid = self.config['host']['docker_user_uid']
        gid = self.config['host']['docker_user_gid']
        run_cmd(
            ["chown", "-R", f"{uid}:{gid}", str(runner_path)],
            sudo=True,
            sudo_reason=f"setting runner binary ownership to ci-docker user",
            dry_run_msg=f"Set runner directory ownership {uid}:{gid}"
        )

        log(f"Runner binary installed at {runner_path}", "success")

    def register_runner(self, runner: RunnerConfig):
        """Register or reconfigure runner with GitHub"""
        token = os.environ.get("REGISTER_GITHUB_RUNNER_TOKEN")
        if not token and not DRY_RUN:
            log("REGISTER_GITHUB_RUNNER_TOKEN not set - skipping registration", "warning")
            log(f"Runner {runner.registered_name} must already be registered", "warning")
            return

        log(f"Registering {runner.registered_name}...", "info")

        runner_path = Path(runner.runner_path)
        org = self.config['github']['org']
        runner_url = f"https://github.com/{org}"

        log_debug(f"Runner URL: {runner_url}")
        log_debug(f"Runner name: {runner.registered_name}")
        log_debug(f"Labels: {runner.labels}")

        # Check if runner needs (re)configuration
        runner_file = runner_path / ".runner"
        credentials_file = runner_path / ".credentials"
        labels_file = runner_path / ".labels"

        need_config = True

        if not DRY_RUN and runner_file.exists() and credentials_file.exists():
            # Check if labels match
            if labels_file.exists():
                current_labels = labels_file.read_text().strip()
                log_debug(f"Current labels: {current_labels}")
                if current_labels == runner.labels:
                    log(f"Runner {runner.registered_name} already configured with correct labels", "info")
                    need_config = False
                else:
                    log(f"Labels changed, reconfiguring runner...", "info")
                    # Remove existing configuration
                    self._unconfigure_runner(runner, token)
        
        if need_config or DRY_RUN:
            # Run config.sh
            config_cmd = [
                str(runner_path / "config.sh"),
                "--url", runner_url,
                "--token", "***TOKEN***" if DRY_RUN else token,
                "--name", runner.registered_name,
                "--labels", runner.labels,
                "--unattended",
                "--replace"
            ]

            # Run as the runner user
            uid = self.config['host']['docker_user_uid']
            gid = self.config['host']['docker_user_gid']

            log_debug(f"Running config.sh as UID {uid}, GID {gid}")

            # Use sudo -u to run as specific user
            if DRY_RUN:
                log_dry_run(f"Register runner {runner.registered_name} with GitHub")
                log_dry_run(f"Labels: {runner.labels}")
            else:
                try:
                    run_cmd(
                        ["sudo", "-u", f"#{uid}", "-g", f"#{gid}",
                         "bash", "-c", f"cd {shlex.quote(str(runner_path))} && {' '.join(shlex.quote(arg) for arg in config_cmd)}"]
                    )
                except subprocess.CalledProcessError as e:
                    log(f"Failed to register runner {runner.registered_name}", "error")
                    log("This usually means:", "error")
                    log("  • Registration token is invalid or expired", "error")
                    log("  • Token was already used (tokens are single-use)", "error")
                    log("  • Network connectivity issues", "error")
                    log("\nTry fetching a fresh token and re-running", "error")
                    raise

            # Save labels
            if DRY_RUN:
                log_dry_run(f"Save labels to {labels_file}")
            else:
                labels_file.write_text(runner.labels)
                run_cmd(
                    ["chown", f"{uid}:{gid}", str(labels_file)],
                    sudo=True,
                    sudo_reason=f"setting labels file ownership",
                    dry_run_msg=f"Set labels file ownership"
                )

            log(f"Registered {runner.registered_name}", "success")

    def _unconfigure_runner(self, runner: RunnerConfig, token: str):
        """Remove runner configuration"""
        runner_path = Path(runner.runner_path)
        
        log(f"Removing existing configuration for {runner.registered_name}...", "info")
        
        # Try to remove via config.sh
        remove_cmd = [
            str(runner_path / "config.sh"),
            "remove",
            "--token", token
        ]
        
        uid = self.config['host']['docker_user_uid']
        
        try:
            run_cmd(
                ["sudo", "-u", f"#{uid}", "bash", "-c",
                 f"cd {shlex.quote(str(runner_path))} && {' '.join(shlex.quote(arg) for arg in remove_cmd)}"],
                check=False
            )
        except Exception:
            log("Failed to cleanly remove runner, will force cleanup", "warning")
        
        # Clean up config files
        for f in [".runner", ".credentials", ".credentials_rsaparams", ".service", ".labels"]:
            file_path = runner_path / f
            if file_path.exists():
                file_path.unlink()

    def generate_hook_content(self, runner: RunnerConfig):
        """Generate the pre-job cleanup hook script content"""
        runner_path = Path(runner.runner_path)
        work_path = runner_path / "_work"

        uid = self.config['host']['docker_user_uid']
        gid = self.config['host']['docker_user_gid']

        return f"""#!/bin/bash
# Pre-job cleanup hook for GitHub Actions runner
# 1. Fixes workspace permissions to handle root-owned files from Docker
# 2. Removes stale tool installations to prevent cross-container contamination

WORK_DIR="{work_path}"

if [ -d "$WORK_DIR" ]; then
    # Fix ownership of any files not owned by the runner user
    sudo /usr/bin/chown -R {uid}:{gid} "$WORK_DIR" 2>/dev/null || true
fi

# Remove tool installations from previous container runs
# Prevents cross-image contamination (e.g. python:3.12 Poetry crashing in python:3.11)
HOME_LOCAL="{runner_path}/.local"
if [ -d "$HOME_LOCAL" ]; then
    echo "[cleanup-hook] Removing stale $HOME_LOCAL from previous container run"
    # Container jobs run as root, so files may be root-owned — fix ownership first
    sudo /usr/bin/chown -R {uid}:{gid} "$HOME_LOCAL" 2>/dev/null || true
    rm -rf "$HOME_LOCAL" 2>/dev/null || true
fi
"""

    def create_cleanup_hook(self, runner: RunnerConfig):
        """Create a pre-job cleanup script that fixes workspace permissions and removes stale tool installations"""
        runner_path = Path(runner.runner_path)
        hook_path = runner_path / "cleanup-workspace.sh"

        uid = self.config['host']['docker_user_uid']
        gid = self.config['host']['docker_user_gid']

        log(f"Creating cleanup hook for {runner.registered_name}...", "info")

        hook_content = self.generate_hook_content(runner)

        # Write to /tmp first, then copy with sudo
        temp_path = Path(f"/tmp/cleanup-workspace-{os.getpid()}.sh")
        temp_path.write_text(hook_content)
        temp_path.chmod(0o755)

        run_cmd(
            ["cp", str(temp_path), str(hook_path)],
            sudo=True,
            sudo_reason=f"installing cleanup hook script"
        )
        run_cmd(
            ["chown", f"{uid}:{gid}", str(hook_path)],
            sudo=True,
            sudo_reason=f"setting cleanup hook ownership"
        )
        run_cmd(
            ["chmod", "755", str(hook_path)],
            sudo=True,
            sudo_reason=f"setting cleanup hook permissions"
        )
        temp_path.unlink()

        log(f"Cleanup hook created at {hook_path}", "success")

    def generate_sudoers_content(self):
        """Generate the sudoers configuration content"""
        uid = self.config['host']['docker_user_uid']
        gid = self.config['host']['docker_user_gid']
        base = self.config['host']['runner_base']

        return f"""# Allow GitHub Actions runner user to fix workspace and tool installation permissions
# Managed by deploy-host.py - do not edit manually
Defaults:#{uid} !requiretty
#{uid} ALL=(root) NOPASSWD: /usr/bin/chown -R {uid}\\:{gid} {base}/*/_work, /usr/bin/chown -R {uid}\\:{gid} {base}/*/_work/*, /usr/bin/chown -R {uid}\\:{gid} {base}/*/.local
"""

    def configure_sudoers(self):
        """Configure sudoers to allow runner user to fix workspace and tool installation permissions"""
        sudoers_path = Path(self.config['sudoers']['path'])

        log("Configuring sudoers for workspace cleanup...", "info")

        sudoers_content = self.generate_sudoers_content()

        # Write to /tmp first (user-writable), then move with sudo
        temp_path = Path(f"/tmp/gha-runner-cleanup-{os.getpid()}.sudoers")
        temp_path.write_text(sudoers_content)
        temp_path.chmod(0o440)

        # Validate sudoers syntax before installing
        try:
            run_cmd(
                ["visudo", "-c", "-f", str(temp_path)],
                sudo=True,
                sudo_reason="validating sudoers configuration",
                capture=True
            )
        except subprocess.CalledProcessError:
            temp_path.unlink()
            log("Sudoers file validation failed!", "error")
            raise

        # Move into place with sudo
        run_cmd(
            ["cp", str(temp_path), str(sudoers_path)],
            sudo=True,
            sudo_reason="installing sudoers configuration for workspace cleanup"
        )
        run_cmd(
            ["chmod", "440", str(sudoers_path)],
            sudo=True,
            sudo_reason="setting sudoers file permissions"
        )
        temp_path.unlink()
        log("Sudoers configured for workspace cleanup", "success")

    def create_systemd_service(self, runner: RunnerConfig):
        """Create and enable systemd service for runner"""
        log(f"Creating systemd service for {runner.registered_name}...", "info")

        service_name = f"{runner.service_name}.service"
        service_path = Path(f"/etc/systemd/system/{service_name}")

        uid = self.config['host']['docker_user_uid']
        gid = self.config['host']['docker_user_gid']
        runner_path = runner.runner_path
        size_cfg = runner.size_config
        hook_path = f"{runner_path}/cleanup-workspace.sh"

        log_debug(f"Service name: {service_name}")
        log_debug(f"Service path: {service_path}")

        # Build service file content
        service_content = f"""[Unit]
Description=GitHub Actions Runner - {runner.registered_name}
After=network.target

[Service]
Type=simple
User={uid}
Group={gid}
WorkingDirectory={runner_path}
ExecStart={runner_path}/run.sh
Restart={self.config['systemd']['restart_policy']}
RestartSec={self.config['systemd']['restart_sec']}
Environment="HOME={runner_path}"
Environment="XDG_CACHE_HOME={runner_path}/.cache"
Environment="ACTIONS_RUNNER_HOOK_JOB_STARTED={hook_path}"
"""

        # Add resource limits using systemd directives
        if size_cfg.get('cpus'):
            cpu_quota = int(float(size_cfg['cpus']) * 100)
            service_content += f"CPUQuota={cpu_quota}%\n"
            log_debug(f"CPU limit: {size_cfg['cpus']} cores ({cpu_quota}%)")

        if size_cfg.get('mem_limit'):
            service_content += f"MemoryMax={size_cfg['mem_limit']}\n"
            log_debug(f"Memory limit: {size_cfg['mem_limit']}")

        if size_cfg.get('pids_limit'):
            service_content += f"TasksMax={size_cfg['pids_limit']}\n"
            log_debug(f"PIDs limit: {size_cfg['pids_limit']}")

        # Add GPU environment variables if needed
        if runner.parsed['gpu']:
            service_content += "Environment=\"NVIDIA_VISIBLE_DEVICES=all\"\n"
            service_content += "Environment=\"NVIDIA_DRIVER_CAPABILITIES=compute,utility\"\n"
            log_debug("GPU support enabled")

        service_content += """
[Install]
WantedBy=multi-user.target
"""

        # Write service file (write to /tmp first, then copy with sudo)
        if DRY_RUN:
            log_dry_run(f"Write systemd service file to {service_path}")
            if VERBOSE:
                log_debug("Service file content:")
                for line in service_content.split('\n'):
                    if line.strip():
                        log_debug(f"  {line}")
        else:
            temp_path = Path(f"/tmp/gha-service-{os.getpid()}.service")
            temp_path.write_text(service_content)
            temp_path.chmod(0o644)
            run_cmd(
                ["cp", str(temp_path), str(service_path)],
                sudo=True,
                sudo_reason=f"installing systemd service file for {service_name}"
            )
            temp_path.unlink()

        # Reload systemd, enable and start service
        log("Reloading systemd daemon...", "info")
        run_cmd(
            ["systemctl", "daemon-reload"],
            sudo=True,
            sudo_reason="reloading systemd after service file changes",
            dry_run_msg="Reload systemd daemon"
        )

        log(f"Enabling service {service_name}...", "info")
        run_cmd(
            ["systemctl", "enable", service_name],
            sudo=True,
            sudo_reason=f"enabling systemd service {service_name}",
            dry_run_msg=f"Enable service {service_name}"
        )

        log(f"Starting service {service_name}...", "info")
        run_cmd(
            ["systemctl", "restart", service_name],
            sudo=True,
            sudo_reason=f"starting runner service {service_name}",
            dry_run_msg=f"Start service {service_name}"
        )

        log(f"Service {service_name} created and started", "success")

    def sync_labels_via_api(self):
        """Sync labels via GitHub API (requires gh CLI)"""
        if not self.config.get('github_api', {}).get('enforce_labels', False):
            log("Label sync disabled in config", "info")
            return

        if not os.environ.get("REGISTER_GITHUB_RUNNER_TOKEN"):
            log("No registration token - skipping label sync", "info")
            return

        if not shutil.which("gh"):
            log("'gh' CLI not found, skipping label sync", "warning")
            return

        log("Syncing labels via GitHub API...", "header")

        org = self.config['github']['org']

        # Run gh as the original user (not root) to access their gh auth
        sudo_user = os.environ.get('SUDO_USER')
        gh_prefix = []
        if sudo_user and os.geteuid() == 0:
            gh_prefix = ["sudo", "-u", sudo_user]

        for runner in self.runners:
            try:
                cmd = gh_prefix + ["gh", "api", f"/orgs/{org}/actions/runners",
                     "--jq", f'.runners[] | select(.name=="{runner.registered_name}") | .id']
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                runner_id = result.stdout.strip()

                if not runner_id:
                    log(f"Runner {runner.registered_name} not found in org, skipping", "warning")
                    continue

                # Update labels (filter out read-only labels that GitHub assigns automatically)
                readonly_labels = {'self-hosted', 'linux', 'macOS', 'windows', 'x64', 'arm64'}
                labels = [l for l in runner.labels.split(',') if l not in readonly_labels]
                labels_json = json.dumps({"labels": labels})

                cmd = gh_prefix + ["gh", "api", "-X", "PUT", f"/orgs/{org}/actions/runners/{runner_id}/labels", "--input", "-"]
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                stdout, stderr = proc.communicate(input=labels_json)

                if proc.returncode != 0:
                    raise Exception(f"gh api failed: {stderr}")

                log(f"Synced labels for {runner.registered_name}", "success")

            except Exception as e:
                log(f"Failed to sync labels for {runner.registered_name}: {e}", "warning")

    def print_summary(self):
        """Print deployment summary"""
        org = self.config['github']['org']
        settings_url = f"https://github.com/organizations/{org}/settings/actions/runners"
        removed = getattr(self, '_removed_runners', [])

        log("\n" + "="*60, "header")
        if DRY_RUN:
            log("DRY-RUN COMPLETE - No changes were made", "header")
        else:
            log("DEPLOYMENT COMPLETE", "header")
        log("="*60, "header")

        # Removed runners
        if removed:
            log(f"\nRemoved {len(removed)} runner(s):", "warning")
            for name in removed:
                log(f"  - {name} (deregistered from GitHub + local cleanup)", "warning")

        # Deployed runners
        if DRY_RUN:
            log(f"\nWould deploy {len(self.runners)} runner(s):", "info")
        else:
            log(f"\nDeployed {len(self.runners)} runner(s):", "info")

        for runner in self.runners:
            log(f"  + {runner.registered_name} ({runner.parsed['type']}, {runner.parsed['size']})", "success")
            log(f"    Service: {runner.service_name}.service", "info")
            log(f"    Path:    {runner.runner_path}", "info")
            if runner.size_config.get('cpus'):
                log(f"    Resources: {runner.size_config['cpus']} CPUs, {runner.size_config.get('mem_limit', 'unlimited')} RAM", "info")

        # Final state
        log(f"\nFinal state: {len(self.runners)} active runner(s)", "info")
        log(f"GitHub:  {settings_url}", "info")

        if DRY_RUN:
            log("\nThis was a dry-run. To deploy for real, run without --dry-run:", "info")
            log("   ./deploy-host.py", "info")
        else:
            log("\nManagement:", "info")
            log("  Check status:   sudo systemctl status gha-*", "info")
            log("  View logs:      sudo journalctl -u gha-* -f", "info")
            log("  Restart runner: sudo systemctl restart gha-<name>", "info")

        log("\n" + "="*60 + "\n", "header")

    def _deregister_runner_from_github(self, runner_name, runner_path):
        """Deregister a runner from GitHub before local removal.

        Tries config.sh remove first (clean deregistration), then falls back
        to the GitHub API if the runner directory or binary is missing.
        """
        token = os.environ.get("REGISTER_GITHUB_RUNNER_TOKEN")
        org = self.config['github']['org']
        uid = self.config['host']['docker_user_uid']
        registered_name = f"{self.config['github']['prefix']}-linux-{runner_name}"
        config_script = runner_path / "config.sh"

        # Try config.sh remove first (cleanest approach)
        if token and config_script.exists():
            log(f"Deregistering {registered_name} from GitHub via config.sh...", "info")
            remove_cmd = [
                str(config_script), "remove", "--token", token
            ]
            try:
                run_cmd(
                    ["sudo", "-u", f"#{uid}", "bash", "-c",
                     f"cd {shlex.quote(str(runner_path))} && {' '.join(shlex.quote(arg) for arg in remove_cmd)}"],
                    check=False
                )
                log(f"Deregistered {registered_name} from GitHub", "success")
                return True
            except Exception:
                log(f"config.sh remove failed, trying GitHub API fallback...", "warning")

        # Fallback: remove via GitHub API
        log(f"Deregistering {registered_name} from GitHub via API...", "info")
        try:
            # Look up runner ID by name
            sudo_user = os.environ.get('SUDO_USER')
            gh_prefix = []
            if sudo_user and os.geteuid() == 0:
                gh_prefix = ["sudo", "-u", sudo_user]

            result = run_cmd(
                gh_prefix + ["gh", "api", f"/orgs/{org}/actions/runners",
                             "--paginate", "--jq",
                             f'.runners[] | select(.name == "{registered_name}") | .id'],
                capture=True,
                check=False
            )
            runner_id = result.stdout.strip()

            if runner_id:
                run_cmd(
                    gh_prefix + ["gh", "api", "-X", "DELETE",
                                 f"/orgs/{org}/actions/runners/{runner_id}"],
                    check=False
                )
                log(f"Deregistered {registered_name} (ID: {runner_id}) from GitHub", "success")
                return True
            else:
                log(f"Runner {registered_name} not found on GitHub (may already be removed)", "info")
                return True

        except Exception as e:
            log(f"Failed to deregister {registered_name} from GitHub: {e}", "warning")
            log(f"  You may need to manually remove it from:", "warning")
            log(f"  https://github.com/organizations/{org}/settings/actions/runners", "warning")
            return False

    def cleanup_removed_runners(self):
        """Remove runners that are no longer in config (local + GitHub)"""
        log("\nChecking for runners to remove...", "info")

        prefix = self.config['github']['prefix']
        service_pattern = f"gha-{prefix}-linux-"

        # Get list of configured runner names
        configured_names = {runner.name for runner in self.runners}

        # Find all existing services matching our pattern
        result = run_cmd(
            ["systemctl", "list-units", "--all", "--no-legend", f"{service_pattern}*"],
            sudo=True,
            capture=True,
            check=False
        )

        self._removed_runners = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue

            # Parse service name from systemctl output
            service_full = line.split()[0]
            if not service_full.startswith(service_pattern):
                continue

            # Extract runner name from service name: gha-{prefix}-linux-{name}.service
            runner_name = service_full.replace(service_pattern, "").replace(".service", "")

            # If this runner is no longer in config, remove it
            if runner_name not in configured_names:
                registered_name = f"{prefix}-linux-{runner_name}"
                log(f"\n>>> Removing runner: {registered_name} (not in config)", "warning")
                service_name = f"{service_pattern}{runner_name}.service"
                runner_path = Path(f"{self.config['host']['runner_base']}/{prefix}-linux-{runner_name}")

                # 1. Stop and disable systemd service
                log(f"  Stopping service {service_name}...", "info")
                run_cmd(
                    ["systemctl", "stop", service_name],
                    sudo=True,
                    sudo_reason=f"stopping removed runner service",
                    check=False
                )

                log(f"  Disabling service {service_name}...", "info")
                run_cmd(
                    ["systemctl", "disable", service_name],
                    sudo=True,
                    sudo_reason=f"disabling removed runner service",
                    check=False
                )

                # 2. Deregister from GitHub (before removing directory)
                self._deregister_runner_from_github(runner_name, runner_path)

                # 3. Remove service file
                service_path = Path(f"/etc/systemd/system/{service_name}")
                if service_path.exists():
                    log(f"  Removing service file {service_path}...", "info")
                    run_cmd(
                        ["rm", str(service_path)],
                        sudo=True,
                        sudo_reason=f"removing systemd service file"
                    )

                # 4. Reload systemd
                run_cmd(
                    ["systemctl", "daemon-reload"],
                    sudo=True,
                    sudo_reason="reloading systemd after removing service"
                )

                # 5. Remove runner directory
                if runner_path.exists():
                    log(f"  Removing runner directory {runner_path}...", "info")
                    run_cmd(
                        ["rm", "-rf", str(runner_path)],
                        sudo=True,
                        sudo_reason=f"removing runner directory {runner_path}"
                    )

                log(f"  Runner {registered_name} fully removed", "success")
                self._removed_runners.append(registered_name)

        if not self._removed_runners:
            log("No runners to remove", "info")
        else:
            log(f"\nRemoved {len(self._removed_runners)} runner(s)", "success")

    def list_runners(self):
        """List all deployed runners with their status"""
        log("Listing deployed runners...\n", "info")
        
        prefix = self.config['github']['prefix']
        service_pattern = f"gha-{prefix}-linux-"
        
        # Get list of all services matching our pattern
        result = run_cmd(
            ["systemctl", "list-units", "--all", "--no-legend", f"{service_pattern}*"],
            sudo=True,
            capture=True,
            check=False
        )
        
        runners_found = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            
            parts = line.split()
            if len(parts) < 4:
                continue
                
            service_full = parts[0]
            if not service_full.startswith(service_pattern):
                continue
            
            # Extract runner name
            runner_name = service_full.replace(service_pattern, "").replace(".service", "")
            
            # Get service status
            status_result = run_cmd(
                ["systemctl", "is-active", service_full],
                sudo=True,
                capture=True,
                check=False
            )
            status = status_result.stdout.strip()
            
            # Get runner path
            runner_path = Path(f"{self.config['host']['runner_base']}/{prefix}-linux-{runner_name}")
            exists = runner_path.exists()
            
            runners_found.append({
                'name': runner_name,
                'service': service_full,
                'status': status,
                'path': runner_path,
                'exists': exists
            })
        
        if not runners_found:
            log("No runners found", "warning")
            return
        
        # Print table header
        log(f"{'Runner Name':<30} {'Service':<40} {'Status':<15} {'Path Exists':<12}", "header")
        log("-" * 100, "header")

        # Use direct ANSI coloring for the status column to keep table alignment,
        # avoiding log() mid-row (which would add prefixes like [SUCCESS])
        for runner in runners_found:
            if runner['status'] == "active":
                status_ansi = "\033[32m"  # green
            else:
                status_ansi = "\033[33m"  # yellow
            reset_ansi = "\033[0m"

            exists_str = "✓" if runner['exists'] else "✗"
            status_field = f"{runner['status']:<15}"
            colored_status = f"{status_ansi}{status_field}{reset_ansi}"

            row = (
                f"{runner['name']:<30} "
                f"{runner['service']:<40} "
                f"{colored_status} "
                f"{exists_str:<12}"
            )
            print(row)
        
        log(f"\nTotal runners: {len(runners_found)}", "info")

    def remove_runner(self, runner_name: str):
        """Remove a specific runner by name"""
        log(f"Removing runner: {runner_name}\n", "warning")

        # Validate runner_name to prevent path traversal attacks
        # Only allow alphanumeric, hyphens, and underscores
        if not re.match(r'^[a-zA-Z0-9_-]+$', runner_name):
            log(f"Invalid runner name '{runner_name}': only alphanumeric, hyphens, and underscores allowed", "error")
            return False

        prefix = self.config['github']['prefix']
        service_name = f"gha-{prefix}-linux-{runner_name}.service"
        runner_path = Path(f"{self.config['host']['runner_base']}/{prefix}-linux-{runner_name}")
        
        # Check if service exists
        check_result = run_cmd(
            ["systemctl", "list-units", "--all", "--no-legend", service_name],
            sudo=True,
            capture=True,
            check=False
        )
        
        if not check_result.stdout.strip():
            log(f"Runner '{runner_name}' not found", "error")
            return False
        
        # 1. Stop and disable service
        log(f"Stopping service {service_name}...", "info")
        run_cmd(
            ["systemctl", "stop", service_name],
            sudo=True,
            sudo_reason=f"stopping runner service {service_name}",
            check=False
        )

        log(f"Disabling service {service_name}...", "info")
        run_cmd(
            ["systemctl", "disable", service_name],
            sudo=True,
            sudo_reason=f"disabling runner service {service_name}",
            check=False
        )

        # 2. Deregister from GitHub (before removing directory)
        self._deregister_runner_from_github(runner_name, runner_path)

        # 3. Remove service file
        service_path = Path(f"/etc/systemd/system/{service_name}")
        if service_path.exists():
            log(f"Removing service file {service_path}...", "info")
            run_cmd(
                ["rm", str(service_path)],
                sudo=True,
                sudo_reason=f"removing systemd service file"
            )

        # 4. Reload systemd
        run_cmd(
            ["systemctl", "daemon-reload"],
            sudo=True,
            sudo_reason="reloading systemd after removing service"
        )

        # 5. Remove runner directory
        if runner_path.exists():
            log(f"Removing runner directory {runner_path}...", "info")
            run_cmd(
                ["rm", "-rf", str(runner_path)],
                sudo=True,
                sudo_reason=f"removing runner directory {runner_path}"
            )

        registered_name = f"{prefix}-linux-{runner_name}"
        log(f"\nRunner '{registered_name}' fully removed (GitHub + local)", "success")
        return True

    def upgrade_runners(self):
        """Upgrade runner binaries for all deployed runners"""
        log("Upgrading runner binaries...\n", "info")
        
        prefix = self.config['github']['prefix']
        service_pattern = f"gha-{prefix}-linux-"
        
        # Get list of all services
        result = run_cmd(
            ["systemctl", "list-units", "--all", "--no-legend", f"{service_pattern}*"],
            sudo=True,
            capture=True,
            check=False
        )
        
        runners_to_upgrade = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            
            parts = line.split()
            if len(parts) < 1:
                continue
                
            service_full = parts[0]
            if not service_full.startswith(service_pattern):
                continue
            
            # Extract runner name
            runner_name = service_full.replace(service_pattern, "").replace(".service", "")
            runner_path = Path(f"{self.config['host']['runner_base']}/{prefix}-linux-{runner_name}")
            
            if runner_path.exists():
                runners_to_upgrade.append({
                    'name': runner_name,
                    'service': service_full,
                    'path': runner_path
                })
        
        if not runners_to_upgrade:
            log("No runners found to upgrade", "warning")
            return
        
        log(f"Found {len(runners_to_upgrade)} runner(s) to upgrade", "info")

        # Get runner version and download URL from config
        runner_cfg = self.config.get('runner', {})
        runner_version = runner_cfg['version']
        runner_arch = runner_cfg.get('arch', 'linux-x64')
        download_url_template = runner_cfg.get(
            'download_url_template',
            "https://github.com/actions/runner/releases/download/v{version}/actions-runner-{arch}-{version}.tar.gz",
        )
        runner_url = download_url_template.format(version=runner_version, arch=runner_arch)
        runner_tarball = f"/tmp/actions-runner-{runner_arch}-{runner_version}.tar.gz"
        
        log(f"\nDownloading runner version {runner_version}...", "info")
        if not Path(runner_tarball).exists():
            run_cmd(
                ["curl", "-L", "-o", runner_tarball, runner_url],
                check=True
            )
        else:
            log(f"Using cached runner tarball: {runner_tarball}", "info")
        
        # Upgrade each runner
        upgraded_count = 0
        for runner_info in runners_to_upgrade:
            log(f"\n>>> Upgrading runner: {runner_info['name']}", "header")
            
            # Stop service
            log(f"Stopping service {runner_info['service']}...", "info")
            run_cmd(
                ["systemctl", "stop", runner_info['service']],
                sudo=True,
                sudo_reason=f"stopping runner for upgrade",
                check=False
            )
            
            # Backup current version (just the binaries, not _work)
            backup_marker = runner_info['path'] / ".backup-done"
            if not backup_marker.exists():
                log(f"Creating backup of runner binaries...", "info")
                run_cmd(
                    ["tar", "-czf", f"{runner_info['path']}.backup.tar.gz",
                     "-C", str(runner_info['path']),
                     "--exclude=_work", "--exclude=.runner",
                     "."],
                    sudo=True,
                    sudo_reason="backing up runner before upgrade"
                )
                run_cmd(
                    ["touch", str(backup_marker)],
                    sudo=True,
                    sudo_reason="creating backup marker after runner backup"
                )
            
            # Extract new binaries (preserve _work and .runner)
            log(f"Extracting new runner binaries...", "info")
            run_cmd(
                ["tar", "-xzf", runner_tarball, 
                 "-C", str(runner_info['path']),
                 "--exclude=_work", "--exclude=.runner"],
                sudo=True,
                sudo_reason="extracting new runner binaries"
            )
            
            # Fix permissions
            runner_uid = self.config['host'].get('docker_user_uid', 1003)
            runner_gid = self.config['host'].get('docker_user_gid', 1003)
            run_cmd(
                ["chown", "-R", f"{runner_uid}:{runner_gid}", str(runner_info['path'])],
                sudo=True,
                sudo_reason="fixing permissions after upgrade"
            )
            
            # Start service
            log(f"Starting service {runner_info['service']}...", "info")
            run_cmd(
                ["systemctl", "start", runner_info['service']],
                sudo=True,
                sudo_reason=f"starting upgraded runner",
                check=False
            )
            
            # Verify it started
            time.sleep(2)
            status_result = run_cmd(
                ["systemctl", "is-active", runner_info['service']],
                sudo=True,
                capture=True,
                check=False
            )
            
            if status_result.stdout.strip() == "active":
                log(f"✅ Runner '{runner_info['name']}' upgraded successfully", "success")
                upgraded_count += 1
            else:
                log(f"⚠️  Runner '{runner_info['name']}' upgraded but failed to start", "warning")
        
        log(f"\n✅ Upgraded {upgraded_count}/{len(runners_to_upgrade)} runner(s)", "success")

    def deploy(self):
        """Main deployment workflow"""
        log("Starting GitHub Actions Host-Based Runner Deployment", "header")
        log(f"Config: {self.config_path}", "info")
        log(f"Version: {self.version_tag}\n", "info")

        check_requirements()

        # Ensure we have a GitHub registration token
        if not self.ensure_github_token():
            log("\nDeployment aborted: No registration token available", "error")
            log("Please either:", "error")
            log("  1. Set REGISTER_GITHUB_RUNNER_TOKEN environment variable, or", "error")
            log("  2. Authenticate with 'gh auth login' to fetch automatically", "error")
            sys.exit(1)

        self.ensure_directories()
        self.cleanup_removed_runners()
        self.configure_sudoers()

        for runner in self.runners:
            log(f"\n>>> Deploying runner: {runner.registered_name}", "header")
            self.install_dependencies(runner)
            self.install_runner_binary(runner)
            self.register_runner(runner)
            self.create_cleanup_hook(runner)
            self.create_systemd_service(runner)

        self.sync_labels_via_api()
        self.print_summary()


def main():
    """Entry point"""
    parser = argparse.ArgumentParser(
        description="Deploy GitHub Actions self-hosted runners",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate configuration without deploying
  ./deploy-host.py --validate

  # Preview what would be deployed (dry-run)
  ./deploy-host.py --dry-run

  # Deploy runners (will prompt for sudo password when needed)
  ./deploy-host.py

  # List all deployed runners
  ./deploy-host.py --list

  # Remove a specific runner
  ./deploy-host.py --remove cpu-small-1

  # Upgrade all runner binaries
  ./deploy-host.py --upgrade

  # Deploy with verbose output
  ./deploy-host.py --verbose

  # Deploy with custom config file
  ./deploy-host.py --config custom-config.yml

  # Combine flags
  ./deploy-host.py --validate --verbose
  ./deploy-host.py --dry-run --verbose

Note: The script will prompt for sudo password when needed for system operations
      (creating directories, systemd services, etc.). You do NOT need to run
      the entire script with sudo.
        """
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate configuration without deploying'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview deployment actions without executing them'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List all deployed runners with their status'
    )
    parser.add_argument(
        '--remove',
        metavar='RUNNER_NAME',
        help='Remove a specific runner (e.g., cpu-small-1)'
    )
    parser.add_argument(
        '--upgrade',
        action='store_true',
        help='Upgrade runner binaries for all deployed runners'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output with detailed logging'
    )
    parser.add_argument(
        '--config',
        default='config.yml',
        help='Path to configuration file (default: config.yml)'
    )

    args = parser.parse_args()

    # Set global flags
    global VERBOSE, DRY_RUN
    VERBOSE = args.verbose
    DRY_RUN = args.dry_run

    if VERBOSE:
        log("Verbose mode enabled", "debug")
    if DRY_RUN:
        log("Dry-run mode enabled - no changes will be made", "info")

    try:
        deployer = HostDeployer(config_path=args.config)

        # Handle --list command
        if args.list:
            deployer.list_runners()
            sys.exit(0)

        # Handle --remove command
        if args.remove:
            if deployer.remove_runner(args.remove):
                sys.exit(0)
            else:
                sys.exit(1)

        # Handle --upgrade command
        if args.upgrade:
            deployer.upgrade_runners()
            sys.exit(0)

        # Handle --validate command
        if args.validate:
            # Validation mode - check config and exit
            log("Running in validation mode (no deployment will occur)\n", "info")
            if deployer.validate_config():
                log("\n✅ Configuration is ready for deployment!", "success")
                sys.exit(0)
            else:
                log("\n❌ Configuration has errors. Fix them before deploying.", "error")
                sys.exit(1)
        else:
            # Normal deployment mode (or dry-run)
            # Validate first before deploying
            if not deployer.validate_config():
                log("\n❌ Configuration validation failed. Aborting deployment.", "error")
                log("Run './deploy-host.py --validate' to see detailed errors.", "info")
                sys.exit(1)

            if DRY_RUN:
                log("\n" + "="*60, "header")
                log("DRY-RUN MODE - Preview of deployment actions", "header")
                log("="*60 + "\n", "header")
            else:
                log("\n" + "="*60, "header")

            deployer.deploy()

    except KeyboardInterrupt:
        log("\nDeployment cancelled by user", "warning")
        sys.exit(1)
    except Exception as e:
        log(f"Deployment failed: {e}", "error")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
