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
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)


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


def log(msg: str, level: str = "info"):
    """Colored logging"""
    colors = {
        "info": Colors.OKBLUE,
        "success": Colors.OKGREEN,
        "warning": Colors.WARNING,
        "error": Colors.FAIL,
        "header": Colors.BOLD + Colors.HEADER,
    }
    color = colors.get(level, "")
    print(f"{color}[{level.upper()}]{Colors.ENDC} {msg}")


def run_cmd(cmd: List[str], check: bool = True, capture: bool = False, sudo: bool = False) -> subprocess.CompletedProcess:
    """Run shell command with error handling"""
    if sudo and os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    
    try:
        if capture:
            return subprocess.run(cmd, check=check, capture_output=True, text=True)
        else:
            return subprocess.run(cmd, check=check)
    except subprocess.CalledProcessError as e:
        log(f"Command failed: {' '.join(cmd)}", "error")
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

        # Ensure base directory exists
        if not base_path.exists():
            log(f"Creating {base}...", "info")
            run_cmd(["mkdir", "-p", str(base_path)], sudo=True)

        # Create individual runner directories
        for runner in self.runners:
            path = Path(runner.runner_path)
            if not path.exists():
                log(f"Creating {path}...", "info")
                run_cmd(["mkdir", "-p", str(path)], sudo=True)

        # Set ownership
        log(f"Setting ownership {uid}:{gid} on {base}...", "info")
        run_cmd(["chown", "-R", f"{uid}:{gid}", str(base_path)], sudo=True)

        # Create shared cache directory for corca-ai/local-cache
        # Used as a general cache across ecosystems (e.g. Poetry, npm, Cargo)
        cache_dir = Path("/srv/gha-cache")
        if not cache_dir.exists():
            log(f"Creating shared cache directory {cache_dir}...", "info")
            run_cmd(["mkdir", "-p", str(cache_dir)], sudo=True)
        # Always ensure correct ownership/permissions (fix if directory exists with wrong perms)
        run_cmd(["chown", f"{uid}:{gid}", str(cache_dir)], sudo=True)
        run_cmd(["chmod", "755", str(cache_dir)], sudo=True)
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
        if config_script.exists():
            log(f"Runner binary already installed at {runner_path}", "info")
            return
        
        log(f"Installing runner binary for {runner.registered_name}...", "info")
        
        version = self.config['runner']['version']
        arch = self.config['runner']['arch']
        tarball_url = f"https://github.com/actions/runner/releases/download/v{version}/actions-runner-{arch}-{version}.tar.gz"
        tarball_path = runner_path / "runner.tar.gz"
        
        # Download runner tarball
        log(f"Downloading runner v{version}...", "info")
        run_cmd([
            "curl", "-fsSL", "-o", str(tarball_path), tarball_url
        ])
        
        # Extract tarball
        log("Extracting runner...", "info")
        run_cmd([
            "tar", "xzf", str(tarball_path), "-C", str(runner_path)
        ])
        
        # Remove tarball
        tarball_path.unlink()
        
        # Fix ownership
        uid = self.config['host']['docker_user_uid']
        gid = self.config['host']['docker_user_gid']
        run_cmd(["chown", "-R", f"{uid}:{gid}", str(runner_path)], sudo=True)
        
        log(f"Runner binary installed at {runner_path}", "success")

    def register_runner(self, runner: RunnerConfig):
        """Register or reconfigure runner with GitHub"""
        token = os.environ.get("REGISTER_GITHUB_RUNNER_TOKEN")
        if not token:
            log("REGISTER_GITHUB_RUNNER_TOKEN not set - skipping registration", "warning")
            log(f"Runner {runner.registered_name} must already be registered", "warning")
            return
        
        log(f"Registering {runner.registered_name}...", "info")
        
        runner_path = Path(runner.runner_path)
        org = self.config['github']['org']
        runner_url = f"https://github.com/{org}"
        
        # Check if runner needs (re)configuration
        runner_file = runner_path / ".runner"
        credentials_file = runner_path / ".credentials"
        labels_file = runner_path / ".labels"
        
        need_config = True
        
        if runner_file.exists() and credentials_file.exists():
            # Check if labels match
            if labels_file.exists():
                current_labels = labels_file.read_text().strip()
                if current_labels == runner.labels:
                    log(f"Runner {runner.registered_name} already configured with correct labels", "info")
                    need_config = False
                else:
                    log(f"Labels changed, reconfiguring runner...", "info")
                    # Remove existing configuration
                    self._unconfigure_runner(runner, token)
        
        if need_config:
            # Run config.sh
            config_cmd = [
                str(runner_path / "config.sh"),
                "--url", runner_url,
                "--token", token,
                "--name", runner.registered_name,
                "--labels", runner.labels,
                "--unattended",
                "--replace"
            ]
            
            # Run as the runner user
            uid = self.config['host']['docker_user_uid']
            gid = self.config['host']['docker_user_gid']
            
            # Use sudo -u to run as specific user
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
            labels_file.write_text(runner.labels)
            run_cmd(["chown", f"{uid}:{gid}", str(labels_file)], sudo=True)

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

    def create_cleanup_hook(self, runner: RunnerConfig):
        """Create a pre-job cleanup script that fixes workspace permissions"""
        runner_path = Path(runner.runner_path)
        hook_path = runner_path / "cleanup-workspace.sh"
        work_path = runner_path / "_work"

        uid = self.config['host']['docker_user_uid']
        gid = self.config['host']['docker_user_gid']

        log(f"Creating cleanup hook for {runner.registered_name}...", "info")

        hook_content = f"""#!/bin/bash
# Pre-job cleanup hook for GitHub Actions runner
# Fixes workspace permissions before each job to handle root-owned files from Docker

WORK_DIR="{work_path}"

if [ -d "$WORK_DIR" ]; then
    # Fix ownership of any files not owned by the runner user
    sudo /usr/bin/chown -R {uid}:{gid} "$WORK_DIR" 2>/dev/null || true
fi
"""

        # Write to /tmp first, then copy with sudo
        temp_path = Path(f"/tmp/cleanup-workspace-{os.getpid()}.sh")
        temp_path.write_text(hook_content)
        temp_path.chmod(0o755)

        run_cmd(["cp", str(temp_path), str(hook_path)], sudo=True)
        run_cmd(["chown", f"{uid}:{gid}", str(hook_path)], sudo=True)
        run_cmd(["chmod", "755", str(hook_path)], sudo=True)
        temp_path.unlink()

        log(f"Cleanup hook created at {hook_path}", "success")

    def configure_sudoers(self):
        """Configure sudoers to allow runner user to fix workspace permissions"""
        uid = self.config['host']['docker_user_uid']
        gid = self.config['host']['docker_user_gid']
        base = self.config['host']['runner_base']
        sudoers_path = Path("/etc/sudoers.d/gha-runner-cleanup")

        log("Configuring sudoers for workspace cleanup...", "info")

        # Allow the runner user to run chown on the runner base directory without password
        sudoers_content = f"""# Allow GitHub Actions runner user to fix workspace permissions
# Managed by deploy-host.py - do not edit manually
Defaults:#{uid} !requiretty
#{uid} ALL=(root) NOPASSWD: /usr/bin/chown -R {uid}\\:{gid} {base}/*/_work, /usr/bin/chown -R {uid}\\:{gid} {base}/*/_work/*
"""

        # Write to /tmp first (user-writable), then move with sudo
        temp_path = Path(f"/tmp/gha-runner-cleanup-{os.getpid()}.sudoers")
        temp_path.write_text(sudoers_content)
        temp_path.chmod(0o440)

        # Validate sudoers syntax before installing
        try:
            run_cmd(["visudo", "-c", "-f", str(temp_path)], sudo=True, capture=True)
        except subprocess.CalledProcessError:
            temp_path.unlink()
            log("Sudoers file validation failed!", "error")
            raise

        # Move into place with sudo
        run_cmd(["cp", str(temp_path), str(sudoers_path)], sudo=True)
        run_cmd(["chmod", "440", str(sudoers_path)], sudo=True)
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
Restart=always
RestartSec=10
Environment="HOME={runner_path}"
Environment="XDG_CACHE_HOME={runner_path}/.cache"
Environment="ACTIONS_RUNNER_HOOK_JOB_STARTED={hook_path}"
"""

        # Add resource limits using systemd directives
        if size_cfg.get('cpus'):
            cpu_quota = int(float(size_cfg['cpus']) * 100)
            service_content += f"CPUQuota={cpu_quota}%\n"

        if size_cfg.get('mem_limit'):
            service_content += f"MemoryMax={size_cfg['mem_limit']}\n"

        if size_cfg.get('pids_limit'):
            service_content += f"TasksMax={size_cfg['pids_limit']}\n"

        # Add GPU environment variables if needed
        if runner.parsed['gpu']:
            service_content += "Environment=\"NVIDIA_VISIBLE_DEVICES=all\"\n"
            service_content += "Environment=\"NVIDIA_DRIVER_CAPABILITIES=compute,utility\"\n"

        service_content += """
[Install]
WantedBy=multi-user.target
"""
        
        # Write service file
        service_path.write_text(service_content)
        
        # Reload systemd, enable and start service
        log("Reloading systemd daemon...", "info")
        run_cmd(["systemctl", "daemon-reload"], sudo=True)
        
        log(f"Enabling service {service_name}...", "info")
        run_cmd(["systemctl", "enable", service_name], sudo=True)
        
        log(f"Starting service {service_name}...", "info")
        run_cmd(["systemctl", "restart", service_name], sudo=True)
        
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
        log("\n" + "="*60, "header")
        log("DEPLOYMENT COMPLETE", "header")
        log("="*60, "header")

        org = self.config['github']['org']
        settings_url = f"https://github.com/organizations/{org}/settings/actions/runners"

        log(f"\nRunners: {settings_url}", "info")
        log(f"\nDeployed {len(self.runners)} runner(s):", "info")

        for runner in self.runners:
            log(f"  • {runner.registered_name} ({runner.parsed['type']}, {runner.parsed['size']})", "info")
            log(f"    Service: {runner.service_name}.service", "info")
            log(f"    Path: {runner.runner_path}", "info")

        log("\nManagement commands:", "info")
        log("  • Check status: sudo systemctl status gha-*", "info")
        log("  • View logs: sudo journalctl -u gha-* -f", "info")
        log("  • Restart runner: sudo systemctl restart gha-<name>", "info")

        log("\n" + "="*60 + "\n", "header")

    def cleanup_removed_runners(self):
        """Remove runners that are no longer in config"""
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

        removed_count = 0
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
                log(f"\n>>> Removing runner: {runner_name}", "warning")
                service_name = f"{service_pattern}{runner_name}.service"
                runner_path = Path(f"{self.config['host']['runner_base']}/{prefix}-linux-{runner_name}")

                # Stop and disable service
                log(f"Stopping service {service_name}...", "info")
                run_cmd(["systemctl", "stop", service_name], sudo=True, check=False)

                log(f"Disabling service {service_name}...", "info")
                run_cmd(["systemctl", "disable", service_name], sudo=True, check=False)

                # Remove service file
                service_path = Path(f"/etc/systemd/system/{service_name}")
                if service_path.exists():
                    log(f"Removing service file {service_path}...", "info")
                    run_cmd(["rm", str(service_path)], sudo=True)

                # Reload systemd
                run_cmd(["systemctl", "daemon-reload"], sudo=True)

                # Remove runner directory
                if runner_path.exists():
                    log(f"Removing runner directory {runner_path}...", "info")
                    run_cmd(["rm", "-rf", str(runner_path)], sudo=True)

                log(f"Runner {runner_name} removed successfully", "success")
                removed_count += 1

        if removed_count == 0:
            log("No runners to remove", "info")
        else:
            log(f"\nRemoved {removed_count} runner(s)", "success")

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
    try:
        deployer = HostDeployer()
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
