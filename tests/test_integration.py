#!/usr/bin/env python3
"""
Integration tests for gha-runnerd deployment script.

These tests validate:
- Configuration parsing and validation
- Runner name parsing and label generation
- Command-line argument handling
"""

import unittest
from unittest.mock import patch, MagicMock
import subprocess
import tempfile
import os
import sys
import re
from fnmatch import fnmatch
from pathlib import Path

# Add parent directory to path to import deploy-host module
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

# Import from deploy-host.py
# We need to handle this carefully since deploy-host.py is not a module
import importlib.util
spec = importlib.util.spec_from_file_location(
    "deploy_host",
    Path(__file__).parent.parent / "deploy-host.py"
)
deploy_host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy_host)

RunnerConfig = deploy_host.RunnerConfig
HostDeployer = deploy_host.HostDeployer


class TestConfigParsing(unittest.TestCase):
    """Test configuration file parsing and validation"""

    def setUp(self):
        """Create temporary config files for testing"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"

    def tearDown(self):
        """Clean up temporary files"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_config(self, config_dict):
        """Helper to write config to file"""
        with open(self.config_file, 'w') as f:
            yaml.dump(config_dict, f)

    def test_valid_minimal_config(self):
        """Test that a minimal valid config loads successfully"""
        config = {
            'github': {
                'org': 'test-org',
                'prefix': 'test'
            },
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host'
            },
            'cache': {
                'base_dir': '/srv/gha-cache',
                'permissions': '755'
            },
            'runners': ['cpu-small-1'],
            'sizes': {
                'small': {
                    'cpus': 2.0,
                    'mem_limit': '4g'
                }
            },
            'runner': {
                'version': '2.321.0',
                'arch': 'linux-x64'
            }
        }
        self._write_config(config)
        
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertIsNotNone(deployer.config)
        self.assertEqual(deployer.config['github']['org'], 'test-org')
        self.assertEqual(len(deployer.runners), 1)

    def test_invalid_config_missing_required_fields(self):
        """Test that configs missing required fields are rejected"""
        config = {
            'github': {
                'org': 'test-org'
                # Missing 'prefix'
            },
            'runners': ['cpu-small-1']
        }
        self._write_config(config)
        
        with self.assertRaises((KeyError, AssertionError, SystemExit)):
            deployer = HostDeployer(config_path=str(self.config_file))
            deployer.validate_config()

    def test_config_with_gpu_runner(self):
        """Test config parsing with GPU runner"""
        config = {
            'github': {
                'org': 'test-org',
                'prefix': 'test'
            },
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host'
            },
            'cache': {
                'base_dir': '/srv/gha-cache',
                'permissions': '755'
            },
            'runners': ['gpu-max-1'],
            'sizes': {
                'max': {
                    'cpus': 16.0,
                    'mem_limit': '64g'
                }
            },
            'runner': {
                'version': '2.321.0',
                'arch': 'linux-x64'
            }
        }
        self._write_config(config)
        
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertEqual(len(deployer.runners), 1)
        runner = deployer.runners[0]
        self.assertEqual(runner.parsed['type'], 'gpu')
        self.assertEqual(runner.parsed['size'], 'max')

    def test_config_with_multiple_runners(self):
        """Test config with multiple runners of different types"""
        config = {
            'github': {
                'org': 'test-org',
                'prefix': 'test'
            },
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host'
            },
            'cache': {
                'base_dir': '/srv/gha-cache',
                'permissions': '755'
            },
            'runners': [
                'cpu-small-1',
                'cpu-medium-1',
                'cpu-large-docker-1',
                'gpu-max-1'
            ],
            'sizes': {
                'small': {'cpus': 2.0, 'mem_limit': '4g'},
                'medium': {'cpus': 6.0, 'mem_limit': '16g'},
                'large': {'cpus': 12.0, 'mem_limit': '32g'},
                'max': {'cpus': 16.0, 'mem_limit': '64g'}
            },
            'runner': {
                'version': '2.321.0',
                'arch': 'linux-x64'
            }
        }
        self._write_config(config)

        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertEqual(len(deployer.runners), 4)


class TestRunnerNameParsing(unittest.TestCase):
    """Test runner name parsing and label generation"""

    def _create_runner(self, name):
        """Helper to create a RunnerConfig with minimal config"""
        config = {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {'runner_base': '/srv/gha'},
            'sizes': {
                'small': {'cpus': 2.0, 'mem_limit': '4g'},
                'medium': {'cpus': 6.0, 'mem_limit': '16g'},
                'large': {'cpus': 12.0, 'mem_limit': '32g'},
                'max': {'cpus': 16.0, 'mem_limit': '64g'}
            }
        }
        return RunnerConfig(name, config)

    def test_parse_cpu_generic_runner(self):
        """Test parsing of CPU generic runner name"""
        runner = self._create_runner('cpu-small-1')
        
        self.assertEqual(runner.parsed['type'], 'cpu')
        self.assertEqual(runner.parsed['size'], 'small')
        self.assertEqual(runner.parsed['category'], None)
        self.assertEqual(runner.parsed['number'], '1')
        self.assertEqual(runner.name, 'cpu-small-1')

    def test_parse_cpu_specialized_runner(self):
        """Test parsing of CPU specialized runner (e.g., docker)"""
        runner = self._create_runner('cpu-medium-docker-1')
        
        self.assertEqual(runner.parsed['type'], 'cpu')
        self.assertEqual(runner.parsed['size'], 'medium')
        self.assertEqual(runner.parsed['category'], 'docker')
        self.assertEqual(runner.parsed['number'], '1')

    def test_parse_gpu_runner(self):
        """Test parsing of GPU runner name"""
        runner = self._create_runner('gpu-max-1')
        
        self.assertEqual(runner.parsed['type'], 'gpu')
        self.assertEqual(runner.parsed['size'], 'max')
        self.assertEqual(runner.parsed['category'], None)

    def test_labels_cpu_generic(self):
        """Test label generation for CPU generic runner"""
        # Need to add 'label' to host config for this test
        config = {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {'runner_base': '/srv/gha', 'label': 'test-host'},
            'sizes': {
                'small': {'cpus': 2.0, 'mem_limit': '4g'},
            }
        }
        runner = RunnerConfig('cpu-small-1', config)
        labels = runner.labels
        
        self.assertIn('self-hosted', labels)
        self.assertIn('linux', labels)
        self.assertIn('cpu', labels)
        self.assertIn('small', labels)
        self.assertIn('generic', labels)

    def test_labels_cpu_specialized(self):
        """Test label generation for CPU specialized runner"""
        config = {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {'runner_base': '/srv/gha', 'label': 'test-host'},
            'sizes': {
                'large': {'cpus': 12.0, 'mem_limit': '32g'},
            }
        }
        runner = RunnerConfig('cpu-large-docker-1', config)
        labels = runner.labels
        
        self.assertIn('self-hosted', labels)
        self.assertIn('linux', labels)
        self.assertIn('cpu', labels)
        self.assertIn('large', labels)
        self.assertIn('docker', labels)
        self.assertNotIn('generic', labels)

    def test_labels_gpu_runner(self):
        """Test label generation for GPU runner"""
        config = {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {'runner_base': '/srv/gha', 'label': 'test-host'},
            'sizes': {
                'max': {'cpus': 16.0, 'mem_limit': '64g'},
            }
        }
        runner = RunnerConfig('gpu-max-1', config)
        labels = runner.labels
        
        self.assertIn('self-hosted', labels)
        self.assertIn('linux', labels)
        self.assertIn('gpu', labels)
        self.assertIn('max', labels)
        self.assertIn('generic', labels)

    def test_service_name_generation(self):
        """Test systemd service name generation"""
        config = {
            'github': {'org': 'test-org', 'prefix': 'prod'},
            'host': {'runner_base': '/srv/gha', 'label': 'prod-host'},
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}}
        }
        runner = RunnerConfig('cpu-small-1', config)
        
        expected = 'gha-prod-linux-cpu-small-1'
        self.assertEqual(runner.service_name, expected)

    def test_registered_name_generation(self):
        """Test GitHub registered name generation"""
        config = {
            'github': {'org': 'test-org', 'prefix': 'prod'},
            'host': {'runner_base': '/srv/gha', 'label': 'prod-host'},
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}}
        }
        runner = RunnerConfig('cpu-small-1', config)
        
        expected = 'prod-linux-cpu-small-1'
        self.assertEqual(runner.registered_name, expected)


class TestRunnerValidation(unittest.TestCase):
    """Test runner configuration validation"""

    def _create_runner_with_config(self, name, sizes):
        """Helper to create a RunnerConfig with custom sizes"""
        config = {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {'runner_base': '/srv/gha', 'label': 'test-host'},
            'sizes': sizes
        }
        return RunnerConfig(name, config)

    def test_valid_runner_config(self):
        """Test that valid runner configs pass validation"""
        sizes = {
            'small': {'cpus': 2.0, 'mem_limit': '4g'}
        }
        runner = self._create_runner_with_config('cpu-small-1', sizes)
        # If no exception, validation passed
        self.assertEqual(runner.parsed['size'], 'small')

    def test_invalid_runner_size_not_in_config(self):
        """Test that runner with undefined size is rejected"""
        sizes = {
            'small': {'cpus': 2.0, 'mem_limit': '4g'}
        }
        with self.assertRaises((KeyError, ValueError, AssertionError)):
            runner = self._create_runner_with_config('cpu-medium-1', sizes)
            _ = runner.size_config  # This should trigger validation


class TestCleanupHook(unittest.TestCase):
    """Test pre-job cleanup hook content generation"""

    def setUp(self):
        """Create a HostDeployer with a valid config"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"
        config = {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host'
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'}
        }
        with open(self.config_file, 'w') as f:
            yaml.dump(config, f)
        self.deployer = HostDeployer(config_path=str(self.config_file))
        self.runner = self.deployer.runners[0]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hook_contains_workspace_chown(self):
        """Test that hook fixes ownership of _work directory"""
        content = self.deployer.generate_hook_content(self.runner)
        self.assertIn('sudo /usr/bin/chown -R 1003:1003 "$WORK_DIR"', content)

    def test_hook_cleans_container_home_local(self):
        """Test that hook cleans .local from the container HOME path (_work/_temp/_github_home)"""
        content = self.deployer.generate_hook_content(self.runner)
        runner_path = self.runner.runner_path
        # Container jobs map _work/_temp/_github_home -> /github/home
        self.assertIn(f'CONTAINER_HOME_LOCAL="{runner_path}/_work/_temp/_github_home/.local"', content)
        self.assertIn('rm -rf "$CONTAINER_HOME_LOCAL"', content)

    def test_hook_cleans_host_home_local(self):
        """Test that hook also cleans .local at runner root for non-container jobs"""
        content = self.deployer.generate_hook_content(self.runner)
        runner_path = self.runner.runner_path
        self.assertIn(f'HOME_LOCAL="{runner_path}/.local"', content)
        self.assertIn('rm -rf "$HOME_LOCAL"', content)

    def test_hook_chown_before_rm_for_host_local(self):
        """Test that hook fixes .local ownership before rm -rf for host (non-container) path"""
        content = self.deployer.generate_hook_content(self.runner)
        # chown must appear before rm -rf for .local
        chown_pos = content.index('chown -R 1003:1003 "$HOME_LOCAL"')
        rm_pos = content.index('rm -rf "$HOME_LOCAL"')
        self.assertLess(chown_pos, rm_pos,
                        "chown of .local must run before rm -rf to handle root-owned files")

    def test_hook_workspace_chown_before_container_local_rm(self):
        """Test that workspace chown runs before container .local rm (fixes ownership of _work tree)"""
        content = self.deployer.generate_hook_content(self.runner)
        # The workspace chown -R covers _work/_temp/_github_home/.local,
        # so it must run before the rm -rf of that path
        workspace_chown_pos = content.index('chown -R 1003:1003 "$WORK_DIR"')
        container_rm_pos = content.index('rm -rf "$CONTAINER_HOME_LOCAL"')
        self.assertLess(workspace_chown_pos, container_rm_pos,
                        "workspace chown must run before container .local rm")

    def test_hook_contains_logging(self):
        """Test that hook logs when cleaning .local"""
        content = self.deployer.generate_hook_content(self.runner)
        self.assertIn('echo "[cleanup-hook]', content)

    def test_hook_contains_correct_paths(self):
        """Test that hook uses correct runner-specific paths"""
        content = self.deployer.generate_hook_content(self.runner)
        runner_path = self.runner.runner_path
        self.assertIn(f'WORK_DIR="{runner_path}/_work"', content)
        self.assertIn(f'CONTAINER_HOME_LOCAL="{runner_path}/_work/_temp/_github_home/.local"', content)
        self.assertIn(f'HOME_LOCAL="{runner_path}/.local"', content)

    def test_hook_is_bash_script(self):
        """Test that hook starts with bash shebang"""
        content = self.deployer.generate_hook_content(self.runner)
        self.assertTrue(content.startswith('#!/bin/bash'))

    def test_hook_suppresses_errors(self):
        """Test that hook operations are fault-tolerant (won't fail the job)"""
        content = self.deployer.generate_hook_content(self.runner)
        # All sudo/rm operations should suppress errors:
        # 1. workspace chown, 2. container .local rm, 3. host .local chown, 4. host .local rm
        self.assertEqual(content.count('2>/dev/null || true'), 4,
                         "Expected 4 fault-tolerant operations: workspace chown, "
                         "container .local rm, host .local chown, host .local rm")


class TestSudoersContent(unittest.TestCase):
    """Test sudoers configuration content generation"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"
        config = {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host'
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'}
        }
        with open(self.config_file, 'w') as f:
            yaml.dump(config, f)
        self.deployer = HostDeployer(config_path=str(self.config_file))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sudoers_allows_work_chown(self):
        """Test that sudoers allows chown on _work directories"""
        content = self.deployer.generate_sudoers_content()
        self.assertIn('/srv/gha/*/_work', content)

    def test_sudoers_allows_local_chown(self):
        """Test that sudoers allows chown on .local directories"""
        content = self.deployer.generate_sudoers_content()
        self.assertIn('/srv/gha/*/.local', content)

    def test_sudoers_uses_correct_uid_gid(self):
        """Test that sudoers references the configured uid:gid"""
        content = self.deployer.generate_sudoers_content()
        self.assertIn('#1003 ALL=(root) NOPASSWD:', content)
        self.assertIn('chown -R 1003\\:1003', content)

    def test_sudoers_disables_requiretty(self):
        """Test that sudoers disables requiretty for the runner user"""
        content = self.deployer.generate_sudoers_content()
        self.assertIn('Defaults:#1003 !requiretty', content)


class TestHookSudoersConsistency(unittest.TestCase):
    """P0: Cross-validate that sudo commands in the hook are permitted by sudoers rules.

    The hook generates sudo commands; the sudoers generates NOPASSWD rules.
    If these drift apart, the hook silently fails (because of || true).
    These tests ensure the two stay in sync.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"
        config = {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host'
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'}
        }
        with open(self.config_file, 'w') as f:
            yaml.dump(config, f)
        self.deployer = HostDeployer(config_path=str(self.config_file))
        self.runner = self.deployer.runners[0]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _extract_sudoers_chown_globs(self):
        """Extract the glob patterns from sudoers NOPASSWD chown rules."""
        sudoers = self.deployer.generate_sudoers_content()
        # The sudoers line looks like:
        #   #1003 ALL=(root) NOPASSWD: /usr/bin/chown -R 1003\:1003 /srv/gha/*/_work, ...
        # Extract each chown target path (the glob after uid:gid)
        nopasswd_line = [l for l in sudoers.splitlines() if 'NOPASSWD' in l][0]
        # Split on commas to get individual rules, extract the path from each
        rules = nopasswd_line.split('NOPASSWD:')[1].split(',')
        globs = []
        for rule in rules:
            rule = rule.strip()
            # Each rule is: /usr/bin/chown -R uid\:gid <path>
            parts = rule.rsplit(' ', 1)
            if len(parts) == 2:
                globs.append(parts[1])
        return globs

    def test_sudoers_covers_workspace_chown_command(self):
        """Test that the workspace chown in the hook is permitted by sudoers"""
        hook = self.deployer.generate_hook_content(self.runner)
        globs = self._extract_sudoers_chown_globs()

        # Extract WORK_DIR path from hook
        match = re.search(r'WORK_DIR="([^"]+)"', hook)
        work_dir = match.group(1)

        # The workspace path must match at least one sudoers glob
        self.assertTrue(
            any(fnmatch(work_dir, g) for g in globs),
            f"Hook workspace path '{work_dir}' not covered by sudoers globs: {globs}"
        )

    def test_sudoers_covers_host_local_chown_command(self):
        """Test that the host .local chown in the hook is permitted by sudoers"""
        hook = self.deployer.generate_hook_content(self.runner)
        globs = self._extract_sudoers_chown_globs()

        # Extract HOME_LOCAL path from hook
        match = re.search(r'HOME_LOCAL="([^"]+)"', hook)
        home_local = match.group(1)

        # The .local path must match at least one sudoers glob
        self.assertTrue(
            any(fnmatch(home_local, g) for g in globs),
            f"Hook host .local path '{home_local}' not covered by sudoers globs: {globs}"
        )

    def test_container_home_local_is_under_work_dir(self):
        """Test that container .local is under _work/ so workspace chown covers it.

        The container .local does NOT get its own sudo chown — it relies on
        the recursive workspace chown. If this invariant breaks, the container
        .local rm will silently fail on root-owned files.
        """
        hook = self.deployer.generate_hook_content(self.runner)

        work_dir = re.search(r'WORK_DIR="([^"]+)"', hook).group(1)
        container_local = re.search(r'CONTAINER_HOME_LOCAL="([^"]+)"', hook).group(1)

        self.assertTrue(
            container_local.startswith(work_dir + "/"),
            f"Container .local '{container_local}' is not under work dir '{work_dir}' — "
            f"it needs its own sudo chown or the workspace chown won't cover it"
        )


class TestAsymmetricUidGid(unittest.TestCase):
    """P1: Test that uid and gid are not accidentally swapped or duplicated."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"
        config = {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1001,
                'docker_user_gid': 1002,
                'label': 'test-host'
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'}
        }
        with open(self.config_file, 'w') as f:
            yaml.dump(config, f)
        self.deployer = HostDeployer(config_path=str(self.config_file))
        self.runner = self.deployer.runners[0]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hook_uses_asymmetric_uid_gid(self):
        """Test that hook uses uid:gid (not uid:uid) in chown commands"""
        content = self.deployer.generate_hook_content(self.runner)
        # Must use 1001:1002, not 1001:1001
        self.assertIn('chown -R 1001:1002', content)
        self.assertNotIn('chown -R 1001:1001', content)
        self.assertNotIn('chown -R 1002:1002', content)

    def test_sudoers_uses_asymmetric_uid_gid(self):
        """Test that sudoers uses uid:gid and references uid for user identity"""
        content = self.deployer.generate_sudoers_content()
        # Sudoers escapes colons: 1001\:1002
        self.assertIn('chown -R 1001\\:1002', content)
        self.assertNotIn('chown -R 1001\\:1001', content)
        # User identity uses uid, not gid
        self.assertIn('#1001 ALL=(root)', content)
        self.assertIn('Defaults:#1001', content)


class TestHookSecurityGuardrails(unittest.TestCase):
    """P1: Security guardrails for the cleanup hook."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"
        config = {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host'
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'}
        }
        with open(self.config_file, 'w') as f:
            yaml.dump(config, f)
        self.deployer = HostDeployer(config_path=str(self.config_file))
        self.runner = self.deployer.runners[0]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hook_rm_does_not_use_sudo(self):
        """Test that rm -rf is never called via sudo (chown first, then rm as runner user)"""
        content = self.deployer.generate_hook_content(self.runner)
        for line in content.splitlines():
            if 'rm -rf' in line:
                self.assertNotIn('sudo', line,
                                 f"rm -rf must not use sudo — chown first, then rm as runner user: {line.strip()}")

    def test_hook_host_local_matches_runner_path(self):
        """Test that the hook's host HOME_LOCAL is runner_path/.local (matches systemd HOME)"""
        content = self.deployer.generate_hook_content(self.runner)
        # Match HOME_LOCAL= but not CONTAINER_HOME_LOCAL=
        home_local = re.search(r'\nHOME_LOCAL="([^"]+)"', content).group(1)
        expected = self.runner.runner_path + "/.local"
        self.assertEqual(home_local, expected,
                         "HOME_LOCAL must equal runner_path/.local — "
                         "this is where systemd sets HOME, so host jobs write .local here")


class TestConfigDefaults(unittest.TestCase):
    """Test that config defaults are applied correctly"""

    def test_cache_defaults(self):
        """Test that cache defaults are applied"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump({
                'github': {'org': 'test-org', 'prefix': 'test'},
                'host': {
                    'runner_base': '/srv/gha',
                    'docker_socket': '/var/run/docker.sock',
                    'docker_user_uid': 1003,
                    'docker_user_gid': 1003,
                    'label': 'test-host'
                },
                'cache': {
                    'base_dir': '/srv/gha-cache',
                    'permissions': '755'
                },
                'runners': ['cpu-small-1'],
                'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
                'runner': {'version': '2.321.0', 'arch': 'linux-x64'}
            }, f)
            config_path = f.name
        
        try:
            deployer = HostDeployer(config_path=config_path)
            # Check that cache defaults are applied
            self.assertIn('cache', deployer.config)
            self.assertEqual(deployer.config['cache']['base_dir'], '/srv/gha-cache')
            self.assertEqual(deployer.config['cache']['permissions'], '755')
        finally:
            os.unlink(config_path)


class TestEnterpriseScopeConfig(unittest.TestCase):
    """Test enterprise scope configuration parsing and validation"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_config(self, config_dict):
        with open(self.config_file, 'w') as f:
            yaml.dump(config_dict, f)

    def _base_config(self, **github_overrides):
        """Return a valid base config dict with optional github overrides."""
        github = {
            'org': 'test-org',
            'prefix': 'test',
        }
        github.update(github_overrides)
        return {
            'github': github,
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host',
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'},
        }

    # ----- backward compatibility -----

    def test_default_scope_is_org(self):
        """Existing configs without scope field default to org"""
        self._write_config(self._base_config())
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertEqual(deployer.config['github']['scope'], 'org')

    def test_explicit_org_scope(self):
        """Explicitly setting scope=org works"""
        self._write_config(self._base_config(scope='org'))
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertEqual(deployer.scope, 'org')
        self.assertEqual(deployer.api_base, '/orgs/test-org')
        self.assertEqual(deployer.runner_url, 'https://github.com/test-org')

    # ----- enterprise scope -----

    def test_enterprise_scope_loads(self):
        """Enterprise scope config loads correctly"""
        cfg = self._base_config(
            scope='enterprise',
            enterprise='my-enterprise',
        )
        self._write_config(cfg)
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertEqual(deployer.scope, 'enterprise')
        self.assertEqual(
            deployer.config['github']['enterprise'], 'my-enterprise'
        )

    def test_enterprise_api_base(self):
        """Enterprise scope returns enterprise API base path"""
        cfg = self._base_config(
            scope='enterprise',
            enterprise='my-enterprise',
        )
        self._write_config(cfg)
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertEqual(
            deployer.api_base, '/enterprises/my-enterprise'
        )

    def test_enterprise_runner_url(self):
        """Enterprise scope returns enterprise runner URL"""
        cfg = self._base_config(
            scope='enterprise',
            enterprise='my-enterprise',
        )
        self._write_config(cfg)
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertEqual(
            deployer.runner_url,
            'https://github.com/enterprises/my-enterprise',
        )

    def test_enterprise_scope_missing_enterprise_slug(self):
        """Enterprise scope without enterprise slug exits with error"""
        cfg = self._base_config(scope='enterprise')
        # Remove any enterprise key that might have been set
        cfg['github'].pop('enterprise', None)
        self._write_config(cfg)
        with self.assertRaises(SystemExit):
            HostDeployer(config_path=str(self.config_file))

    def test_invalid_scope_value(self):
        """Invalid scope value exits with error"""
        cfg = self._base_config(scope='invalid')
        self._write_config(cfg)
        with self.assertRaises(SystemExit):
            HostDeployer(config_path=str(self.config_file))

    def test_org_scope_missing_org(self):
        """Org scope without org exits with error"""
        cfg = self._base_config(scope='org')
        cfg['github'].pop('org', None)
        self._write_config(cfg)
        with self.assertRaises(SystemExit):
            HostDeployer(config_path=str(self.config_file))

    # ----- runner_group -----

    def test_runner_group_defaults_to_empty(self):
        """runner_group defaults to empty dict if not specified"""
        self._write_config(self._base_config())
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertEqual(deployer.config['github']['runner_group'], {})

    def test_runner_group_name_parsed(self):
        """runner_group.name is parsed from config"""
        cfg = self._base_config(
            scope='enterprise',
            enterprise='my-enterprise',
            runner_group={'name': 'my-runners'},
        )
        self._write_config(cfg)
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertEqual(
            deployer.config['github']['runner_group']['name'], 'my-runners'
        )

    def test_runner_group_null_normalized_to_empty_dict(self):
        """runner_group: (YAML null) is normalized to empty dict, not AttributeError"""
        cfg = self._base_config()
        cfg['github']['runner_group'] = None
        self._write_config(cfg)
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertEqual(deployer.config['github']['runner_group'], {})

    def test_runner_group_non_dict_rejected(self):
        """runner_group set to a non-dict value (e.g. string) exits with error"""
        cfg = self._base_config()
        cfg['github']['runner_group'] = "not-a-dict"
        self._write_config(cfg)
        with self.assertRaises(SystemExit):
            HostDeployer(config_path=str(self.config_file))

    def test_runner_group_allow_orgs_not_supported(self):
        """runner_group.allow_orgs is rejected by validation (manage in GitHub UI)"""
        cfg = self._base_config(
            scope='enterprise',
            enterprise='my-enterprise',
            runner_group={'name': 'my-runners', 'allow_orgs': ['org-a', 'org-b']},
        )
        self._write_config(cfg)
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertFalse(deployer.validate_config())


class TestEnterpriseScopeValidation(unittest.TestCase):
    """Test enterprise-specific validation rules in validate_config"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_config(self, config_dict):
        with open(self.config_file, 'w') as f:
            yaml.dump(config_dict, f)

    def _enterprise_config(self, **github_overrides):
        github = {
            'scope': 'enterprise',
            'enterprise': 'test-enterprise',
            'prefix': 'test',
        }
        github.update(github_overrides)
        return {
            'github': github,
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host',
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'},
        }

    def test_valid_enterprise_config_passes_validation(self):
        """Valid enterprise config passes validation"""
        self._write_config(self._enterprise_config())
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertTrue(deployer.validate_config())

    def test_enterprise_placeholder_slug_fails_validation(self):
        """Enterprise config with placeholder slug fails validation"""
        cfg = self._enterprise_config(enterprise='your-enterprise')
        self._write_config(cfg)
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertFalse(deployer.validate_config())

    def test_enterprise_empty_slug_caught_at_load(self):
        """Enterprise config with empty slug is caught at load time"""
        cfg = self._enterprise_config(enterprise='')
        self._write_config(cfg)
        with self.assertRaises(SystemExit):
            HostDeployer(config_path=str(self.config_file))

    def test_allow_orgs_rejected_with_ui_link(self):
        """allow_orgs is rejected — org access must be managed in GitHub UI"""
        cfg = self._enterprise_config(
            runner_group={'name': 'my-runners', 'allow_orgs': ['org-a']},
        )
        self._write_config(cfg)
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertFalse(deployer.validate_config())

    def test_runner_group_with_name_only_passes(self):
        """runner_group with just name (no allow_orgs) passes validation"""
        cfg = self._enterprise_config(
            runner_group={'name': 'my-runners'},
        )
        self._write_config(cfg)
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertTrue(deployer.validate_config())

    def test_org_scope_placeholder_still_fails(self):
        """Org scope with placeholder 'your-org' still fails validation"""
        cfg = {
            'github': {'scope': 'org', 'org': 'your-org', 'prefix': 'test'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host',
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'},
        }
        self._write_config(cfg)
        deployer = HostDeployer(config_path=str(self.config_file))
        self.assertFalse(deployer.validate_config())


class TestEnterpriseApiPaths(unittest.TestCase):
    """Test that scope-aware API paths are generated correctly"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_config(self, config_dict):
        with open(self.config_file, 'w') as f:
            yaml.dump(config_dict, f)

    def _make_deployer(self, scope='org', **extra_github):
        github = {'prefix': 'test'}
        if scope == 'org':
            github['scope'] = 'org'
            github['org'] = 'test-org'
        else:
            github['scope'] = 'enterprise'
            github['enterprise'] = 'test-enterprise'
        github.update(extra_github)

        cfg = {
            'github': github,
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host',
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'},
        }
        self._write_config(cfg)
        return HostDeployer(config_path=str(self.config_file))

    def test_org_api_base(self):
        deployer = self._make_deployer('org')
        self.assertEqual(deployer.api_base, '/orgs/test-org')

    def test_enterprise_api_base(self):
        deployer = self._make_deployer('enterprise')
        self.assertEqual(deployer.api_base, '/enterprises/test-enterprise')

    def test_org_runner_url(self):
        deployer = self._make_deployer('org')
        self.assertEqual(deployer.runner_url, 'https://github.com/test-org')

    def test_enterprise_runner_url(self):
        deployer = self._make_deployer('enterprise')
        self.assertEqual(
            deployer.runner_url,
            'https://github.com/enterprises/test-enterprise',
        )

    def test_org_registration_token_path(self):
        """Registration token API path is correct for org scope"""
        deployer = self._make_deployer('org')
        expected = '/orgs/test-org/actions/runners/registration-token'
        self.assertEqual(
            f"{deployer.api_base}/actions/runners/registration-token",
            expected,
        )

    def test_enterprise_registration_token_path(self):
        """Registration token API path is correct for enterprise scope"""
        deployer = self._make_deployer('enterprise')
        expected = '/enterprises/test-enterprise/actions/runners/registration-token'
        self.assertEqual(
            f"{deployer.api_base}/actions/runners/registration-token",
            expected,
        )


class TestDeregistrationFallback(unittest.TestCase):
    """Test that config.sh failure falls through to API-based deregistration"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"
        cfg = {
            'github': {'org': 'test-org', 'prefix': 'test', 'scope': 'org'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host',
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'},
        }
        with open(self.config_file, 'w') as f:
            yaml.dump(cfg, f)
        self.deployer = HostDeployer(config_path=str(self.config_file))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch.dict(os.environ, {"REGISTER_GITHUB_RUNNER_TOKEN": "fake-token"})
    @patch.object(deploy_host, 'run_cmd')
    def test_deregister_falls_through_on_config_sh_failure(self, mock_run_cmd):
        """config.sh returning non-zero should fall through to API fallback"""
        runner_path = Path("/srv/gha/test-linux-cpu-small-1")

        # First call: config.sh remove → returns non-zero
        config_fail = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        # Second call: gh api (list runners) → returns runner id
        api_list = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="12345\n", stderr=""
        )
        # Third call: gh api DELETE → success
        api_delete = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_run_cmd.side_effect = [config_fail, api_list, api_delete]

        with patch.object(Path, 'exists', return_value=True):
            result = self.deployer._deregister_runner_from_github("cpu-small-1", runner_path)

        self.assertTrue(result)
        # Should have called run_cmd 3 times: config.sh, API list, API delete
        self.assertEqual(mock_run_cmd.call_count, 3)
        # Verify the API fallback was reached (second call has 'gh' in args)
        second_call_args = mock_run_cmd.call_args_list[1][0][0]
        self.assertIn("gh", second_call_args)


class TestBusyRunnerProtection(unittest.TestCase):
    """Test that busy runners are not killed during removal"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"
        cfg = {
            'github': {'org': 'test-org', 'prefix': 'test', 'scope': 'org'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host',
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'},
        }
        with open(self.config_file, 'w') as f:
            yaml.dump(cfg, f)
        self.deployer = HostDeployer(config_path=str(self.config_file))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch.object(deploy_host, 'run_cmd')
    def test_busy_runner_skipped_during_cleanup(self, mock_run_cmd):
        """Busy runners should be skipped during cleanup_removed_runners"""
        # systemctl list-units returns an old runner not in config
        list_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="gha-test-linux-old-runner-1.service loaded active running\n",
            stderr=""
        )
        # _is_runner_busy → gh api returns "true"
        busy_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="true\n", stderr=""
        )
        mock_run_cmd.side_effect = [list_result, busy_result]

        self.deployer.cleanup_removed_runners()

        # Only 2 calls: systemctl list + busy check. No stop/disable/deregister.
        self.assertEqual(mock_run_cmd.call_count, 2)
        self.assertEqual(self.deployer._removed_runners, [])

    @patch.object(deploy_host, 'run_cmd')
    def test_idle_runner_removed_during_cleanup(self, mock_run_cmd):
        """Idle runners should be removed normally during cleanup"""
        # systemctl list-units returns an old runner not in config
        list_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="gha-test-linux-old-runner-1.service loaded active running\n",
            stderr=""
        )
        # _is_runner_busy → gh api returns "false"
        idle_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="false\n", stderr=""
        )
        # Remaining calls for the removal process (stop, disable, deregister, etc.)
        generic_ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_run_cmd.side_effect = [list_result, idle_result] + [generic_ok] * 20

        with patch.object(Path, 'exists', return_value=False):
            self.deployer.cleanup_removed_runners()

        # Should have proceeded past the busy check to stop/disable/deregister
        self.assertGreater(mock_run_cmd.call_count, 2)
        self.assertEqual(self.deployer._removed_runners, ["test-linux-old-runner-1"])

    @patch.object(deploy_host, 'run_cmd')
    def test_force_remove_bypasses_busy_check(self, mock_run_cmd):
        """--force should skip the busy check and remove anyway"""
        # systemctl list-units → service exists
        list_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="gha-test-linux-cpu-small-1.service loaded active running\n",
            stderr=""
        )
        generic_ok = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_run_cmd.side_effect = [list_result] + [generic_ok] * 20

        with patch.object(Path, 'exists', return_value=False):
            result = self.deployer.remove_runner("cpu-small-1", force=True)

        self.assertTrue(result)
        # Verify no busy-check call was made (would contain '--jq' with '.busy')
        for call in mock_run_cmd.call_args_list:
            joined = " ".join(str(a) for a in call[0][0])
            self.assertNotIn(".busy", joined)

    @patch.object(deploy_host, 'run_cmd')
    def test_busy_runner_blocked_without_force(self, mock_run_cmd):
        """remove_runner should refuse to remove a busy runner without --force"""
        # systemctl list-units → service exists
        list_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="gha-test-linux-cpu-small-1.service loaded active running\n",
            stderr=""
        )
        # _is_runner_busy → "true"
        busy_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="true\n", stderr=""
        )
        mock_run_cmd.side_effect = [list_result, busy_result]

        result = self.deployer.remove_runner("cpu-small-1", force=False)

        self.assertFalse(result)
        # Only 2 calls: list-units + busy check. No stop/disable.
        self.assertEqual(mock_run_cmd.call_count, 2)


class TestValidationHelpers(unittest.TestCase):
    """Unit tests for validation helper predicates"""

    # -- is_non_negative_int --
    def test_non_negative_int_zero(self):
        self.assertTrue(deploy_host.is_non_negative_int(0))

    def test_non_negative_int_positive(self):
        self.assertTrue(deploy_host.is_non_negative_int(1003))

    def test_non_negative_int_rejects_negative(self):
        self.assertFalse(deploy_host.is_non_negative_int(-1))

    def test_non_negative_int_rejects_bool(self):
        self.assertFalse(deploy_host.is_non_negative_int(True))
        self.assertFalse(deploy_host.is_non_negative_int(False))

    def test_non_negative_int_rejects_float(self):
        self.assertFalse(deploy_host.is_non_negative_int(1.0))

    def test_non_negative_int_rejects_string(self):
        self.assertFalse(deploy_host.is_non_negative_int("1003"))

    # -- is_positive_int --
    def test_positive_int_valid(self):
        self.assertTrue(deploy_host.is_positive_int(1))
        self.assertTrue(deploy_host.is_positive_int(42))

    def test_positive_int_rejects_zero(self):
        self.assertFalse(deploy_host.is_positive_int(0))

    def test_positive_int_rejects_negative(self):
        self.assertFalse(deploy_host.is_positive_int(-5))

    def test_positive_int_rejects_bool(self):
        self.assertFalse(deploy_host.is_positive_int(True))

    def test_positive_int_rejects_string(self):
        self.assertFalse(deploy_host.is_positive_int("10"))

    # -- is_positive_number --
    def test_positive_number_int(self):
        self.assertTrue(deploy_host.is_positive_number(2))

    def test_positive_number_float(self):
        self.assertTrue(deploy_host.is_positive_number(2.5))

    def test_positive_number_rejects_zero(self):
        self.assertFalse(deploy_host.is_positive_number(0))

    def test_positive_number_rejects_negative(self):
        self.assertFalse(deploy_host.is_positive_number(-1.5))

    def test_positive_number_rejects_bool(self):
        self.assertFalse(deploy_host.is_positive_number(True))

    def test_positive_number_rejects_string(self):
        self.assertFalse(deploy_host.is_positive_number("2.5"))

    # -- is_valid_octal_string --
    def test_octal_string_three_digits(self):
        self.assertTrue(deploy_host.is_valid_octal_string("755"))

    def test_octal_string_four_digits(self):
        self.assertTrue(deploy_host.is_valid_octal_string("0755"))

    def test_octal_string_rejects_non_octal(self):
        self.assertFalse(deploy_host.is_valid_octal_string("999"))

    def test_octal_string_rejects_too_short(self):
        self.assertFalse(deploy_host.is_valid_octal_string("75"))

    def test_octal_string_rejects_int(self):
        self.assertFalse(deploy_host.is_valid_octal_string(755))

    # -- is_valid_systemd_memory --
    def test_systemd_memory_valid(self):
        self.assertTrue(deploy_host.is_valid_systemd_memory("4G"))
        self.assertTrue(deploy_host.is_valid_systemd_memory("512M"))
        self.assertTrue(deploy_host.is_valid_systemd_memory("4g"))

    def test_systemd_memory_rejects_bad_suffix(self):
        self.assertFalse(deploy_host.is_valid_systemd_memory("4gb"))
        self.assertFalse(deploy_host.is_valid_systemd_memory("4GB"))

    def test_systemd_memory_rejects_no_suffix(self):
        self.assertFalse(deploy_host.is_valid_systemd_memory("1024"))

    # -- is_valid_service_name_part --
    def test_service_name_valid(self):
        self.assertTrue(deploy_host.is_valid_service_name_part("my"))
        self.assertTrue(deploy_host.is_valid_service_name_part("prod-runners"))

    def test_service_name_rejects_uppercase(self):
        self.assertFalse(deploy_host.is_valid_service_name_part("MyPrefix"))

    def test_service_name_rejects_starting_digit(self):
        self.assertFalse(deploy_host.is_valid_service_name_part("1prefix"))

    def test_service_name_rejects_spaces(self):
        self.assertFalse(deploy_host.is_valid_service_name_part("my prefix"))

    # -- is_absolute_path --
    def test_absolute_path_valid(self):
        self.assertTrue(deploy_host.is_absolute_path("/srv/gha"))

    def test_absolute_path_rejects_relative(self):
        self.assertFalse(deploy_host.is_absolute_path("srv/gha"))
        self.assertFalse(deploy_host.is_absolute_path("./srv/gha"))

    # -- is_valid_slug --
    def test_slug_valid(self):
        self.assertTrue(deploy_host.is_valid_slug("my-org"))
        self.assertTrue(deploy_host.is_valid_slug("org123"))

    def test_slug_rejects_spaces(self):
        self.assertFalse(deploy_host.is_valid_slug("my org"))

    def test_slug_rejects_starting_hyphen(self):
        self.assertFalse(deploy_host.is_valid_slug("-org"))

    # -- is_valid_url_template --
    def test_url_template_valid(self):
        tpl = "https://example.com/{version}/runner-{arch}.tar.gz"
        self.assertTrue(deploy_host.is_valid_url_template(tpl, ['version', 'arch']))

    def test_url_template_missing_placeholder(self):
        tpl = "https://example.com/{version}/runner.tar.gz"
        self.assertFalse(deploy_host.is_valid_url_template(tpl, ['version', 'arch']))

    def test_url_template_rejects_non_string(self):
        self.assertFalse(deploy_host.is_valid_url_template(123, ['version']))


class TestConfigValueValidation(unittest.TestCase):
    """Integration tests: invalid config values detected by validate_config()"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _base_config(self):
        """Return a known-good config dict."""
        return {
            'github': {'org': 'test-org', 'prefix': 'test'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host',
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4G', 'pids_limit': 2048}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'},
        }

    def _validate(self, config):
        """Write config and run validate_config(), return True/False."""
        with open(self.config_file, 'w') as f:
            yaml.dump(config, f)
        deployer = HostDeployer(config_path=str(self.config_file))
        return deployer.validate_config()

    # -- UID/GID --

    def test_uid_zero_accepted(self):
        cfg = self._base_config()
        cfg['host']['docker_user_uid'] = 0
        self.assertTrue(self._validate(cfg))

    def test_uid_string_rejected(self):
        cfg = self._base_config()
        cfg['host']['docker_user_uid'] = "1003"
        self.assertFalse(self._validate(cfg))

    def test_uid_negative_rejected(self):
        cfg = self._base_config()
        cfg['host']['docker_user_uid'] = -1
        self.assertFalse(self._validate(cfg))

    def test_uid_float_rejected(self):
        cfg = self._base_config()
        cfg['host']['docker_user_uid'] = 1003.0
        self.assertFalse(self._validate(cfg))

    def test_gid_zero_accepted(self):
        cfg = self._base_config()
        cfg['host']['docker_user_gid'] = 0
        self.assertTrue(self._validate(cfg))

    def test_gid_string_rejected(self):
        cfg = self._base_config()
        cfg['host']['docker_user_gid'] = "1003"
        self.assertFalse(self._validate(cfg))

    # -- runner_group.name --

    def test_runner_group_name_non_string_rejected(self):
        cfg = self._base_config()
        cfg['github']['scope'] = 'enterprise'
        cfg['github']['enterprise'] = 'test-enterprise'
        cfg['github']['runner_group'] = {'name': 42}
        self.assertFalse(self._validate(cfg))

    def test_runner_group_name_string_accepted(self):
        cfg = self._base_config()
        cfg['github']['scope'] = 'enterprise'
        cfg['github']['enterprise'] = 'test-enterprise'
        cfg['github']['runner_group'] = {'name': 'my-runners'}
        self.assertTrue(self._validate(cfg))

    # -- cpus --

    def test_cpus_string_rejected(self):
        cfg = self._base_config()
        cfg['sizes']['small']['cpus'] = "2"
        self.assertFalse(self._validate(cfg))

    def test_cpus_negative_rejected(self):
        cfg = self._base_config()
        cfg['sizes']['small']['cpus'] = -1.0
        self.assertFalse(self._validate(cfg))

    def test_cpus_null_accepted(self):
        cfg = self._base_config()
        cfg['sizes']['small']['cpus'] = None
        self.assertTrue(self._validate(cfg))

    # -- mem_limit --

    def test_mem_limit_bad_suffix_rejected(self):
        cfg = self._base_config()
        cfg['sizes']['small']['mem_limit'] = "4gb"
        self.assertFalse(self._validate(cfg))

    def test_mem_limit_valid_accepted(self):
        cfg = self._base_config()
        cfg['sizes']['small']['mem_limit'] = "4G"
        self.assertTrue(self._validate(cfg))

    def test_mem_limit_null_accepted(self):
        cfg = self._base_config()
        cfg['sizes']['small']['mem_limit'] = None
        self.assertTrue(self._validate(cfg))

    # -- pids_limit --

    def test_pids_limit_float_rejected(self):
        cfg = self._base_config()
        cfg['sizes']['small']['pids_limit'] = 2048.5
        self.assertFalse(self._validate(cfg))

    def test_pids_limit_null_accepted(self):
        cfg = self._base_config()
        cfg['sizes']['small']['pids_limit'] = None
        self.assertTrue(self._validate(cfg))

    # -- prefix --

    def test_prefix_spaces_rejected(self):
        cfg = self._base_config()
        cfg['github']['prefix'] = "my prefix"
        self.assertFalse(self._validate(cfg))

    def test_prefix_uppercase_rejected(self):
        cfg = self._base_config()
        cfg['github']['prefix'] = "MyPrefix"
        self.assertFalse(self._validate(cfg))

    # -- runner_base --

    def test_runner_base_relative_rejected(self):
        cfg = self._base_config()
        cfg['host']['runner_base'] = "srv/gha"
        self.assertFalse(self._validate(cfg))

    # -- cache.permissions --

    def test_cache_permissions_999_rejected(self):
        cfg = self._base_config()
        cfg['cache']['permissions'] = "999"
        self.assertFalse(self._validate(cfg))

    def test_cache_permissions_0755_accepted(self):
        cfg = self._base_config()
        cfg['cache']['permissions'] = "0755"
        self.assertTrue(self._validate(cfg))

    def test_cache_permissions_yaml_int_coercion(self):
        """YAML may parse unquoted 755 as int — str() conversion handles it."""
        cfg = self._base_config()
        cfg['cache']['permissions'] = 755  # int, not str
        self.assertTrue(self._validate(cfg))

    # -- restart_policy --

    def test_restart_policy_invalid_rejected(self):
        cfg = self._base_config()
        cfg['systemd'] = {'restart_policy': 'sometimes', 'restart_sec': 10}
        self.assertFalse(self._validate(cfg))

    def test_restart_policy_valid_accepted(self):
        cfg = self._base_config()
        cfg['systemd'] = {'restart_policy': 'on-failure', 'restart_sec': 10}
        self.assertTrue(self._validate(cfg))

    # -- restart_sec --

    def test_restart_sec_string_rejected(self):
        cfg = self._base_config()
        cfg['systemd'] = {'restart_policy': 'always', 'restart_sec': "10"}
        self.assertFalse(self._validate(cfg))

    # -- download_url_template --

    def test_download_url_template_missing_placeholders_rejected(self):
        cfg = self._base_config()
        cfg['runner']['download_url_template'] = "https://example.com/runner.tar.gz"
        self.assertFalse(self._validate(cfg))

    def test_download_url_template_valid_accepted(self):
        cfg = self._base_config()
        cfg['runner']['download_url_template'] = (
            "https://example.com/v{version}/runner-{arch}.tar.gz"
        )
        self.assertTrue(self._validate(cfg))

    # -- org/enterprise slugs --

    def test_org_slug_spaces_rejected(self):
        cfg = self._base_config()
        cfg['github']['org'] = "my org"
        self.assertFalse(self._validate(cfg))

    def test_enterprise_slug_spaces_rejected(self):
        cfg = self._base_config()
        cfg['github']['scope'] = 'enterprise'
        cfg['github']['enterprise'] = 'my enterprise'
        self.assertFalse(self._validate(cfg))

    # -- allow_orgs --

    def test_allow_orgs_rejected(self):
        """allow_orgs is not supported — must use GitHub UI."""
        cfg = self._base_config()
        cfg['github']['scope'] = 'enterprise'
        cfg['github']['enterprise'] = 'test-enterprise'
        cfg['github']['runner_group'] = {
            'id': 1,
            'allow_orgs': ['org-a'],
        }
        self.assertFalse(self._validate(cfg))

    # -- cache.base_dir --

    def test_cache_base_dir_relative_rejected(self):
        cfg = self._base_config()
        cfg['cache']['base_dir'] = 'cache/dir'
        self.assertFalse(self._validate(cfg))

    # -- sudoers.path --

    def test_sudoers_path_relative_rejected(self):
        cfg = self._base_config()
        cfg['sudoers'] = {'path': 'sudoers.d/gha'}
        self.assertFalse(self._validate(cfg))

    # -- docker_socket warning --

    def test_docker_socket_produces_warning_but_passes(self):
        """docker_socket triggers a warning but does not fail validation."""
        cfg = self._base_config()
        cfg['host']['docker_socket'] = '/var/run/docker.sock'
        self.assertTrue(self._validate(cfg))

    # -- unknown arch warning --

    def test_unknown_arch_produces_warning_but_passes(self):
        """Unknown arch triggers a warning but does not fail validation."""
        cfg = self._base_config()
        cfg['runner']['arch'] = 'linux-riscv64'
        self.assertTrue(self._validate(cfg))


class TestRunnerConfigFilesConstant(unittest.TestCase):
    """Verify RUNNER_CONFIG_FILES constant is complete and consistent"""

    def test_runner_file_in_list(self):
        """The primary .runner config must be in the list"""
        self.assertIn(".runner", deploy_host.RUNNER_CONFIG_FILES)

    def test_runner_migrated_in_list(self):
        """IsConfigured() checks .runner_migrated — must be in the list"""
        self.assertIn(".runner_migrated", deploy_host.RUNNER_CONFIG_FILES)

    def test_credentials_in_list(self):
        self.assertIn(".credentials", deploy_host.RUNNER_CONFIG_FILES)

    def test_credentials_migrated_in_list(self):
        self.assertIn(".credentials_migrated", deploy_host.RUNNER_CONFIG_FILES)

    def test_credentials_rsaparams_in_list(self):
        self.assertIn(".credentials_rsaparams", deploy_host.RUNNER_CONFIG_FILES)

    def test_credential_store_in_list(self):
        self.assertIn(".credential_store", deploy_host.RUNNER_CONFIG_FILES)

    def test_setup_info_in_list(self):
        self.assertIn(".setup_info", deploy_host.RUNNER_CONFIG_FILES)

    def test_all_entries_are_dotfiles(self):
        """Every config file should be a dotfile"""
        for f in deploy_host.RUNNER_CONFIG_FILES:
            self.assertTrue(f.startswith("."), f"{f} is not a dotfile")

    def test_no_duplicates(self):
        self.assertEqual(
            len(deploy_host.RUNNER_CONFIG_FILES),
            len(set(deploy_host.RUNNER_CONFIG_FILES)),
        )


class TestRegisterRunnerIdempotency(unittest.TestCase):
    """Test that register_runner handles all config files correctly"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"
        cfg = {
            'github': {'org': 'test-org', 'prefix': 'test', 'scope': 'org'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host',
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'},
        }
        with open(self.config_file, 'w') as f:
            yaml.dump(cfg, f)
        self.deployer = HostDeployer(config_path=str(self.config_file))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch.dict(os.environ, {"REGISTER_GITHUB_RUNNER_TOKEN": "fake-token"})
    @patch.object(deploy_host, 'run_cmd')
    def test_rm_command_includes_all_config_files(self, mock_run_cmd):
        """The bash -c shell command must rm every file in RUNNER_CONFIG_FILES"""
        # First call: sudo cat .labels → file not found (needs config)
        mock_run_cmd.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=""
        )

        # _unconfigure_runner calls: systemctl stop, config.sh remove
        # register_runner calls: bash -c (rm + config.sh) → capture the shell_cmd
        def capture_side_effect(cmd, **kwargs):
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        mock_run_cmd.side_effect = capture_side_effect

        runner = self.deployer.runners[0]
        # We expect sys.exit(1) if config.sh fails, but we mock it to succeed
        self.deployer.register_runner(runner)

        # Find the bash -c call that contains rm and config.sh
        shell_calls = [
            call for call in mock_run_cmd.call_args_list
            if any("bash" in str(a) for a in call[0])
            and any("rm" in str(a) for a in call[0])
        ]
        self.assertTrue(len(shell_calls) > 0, "No bash -c call with rm found")
        shell_cmd = str(shell_calls[-1])

        for config_file in deploy_host.RUNNER_CONFIG_FILES:
            self.assertIn(
                config_file, shell_cmd,
                f"{config_file} missing from rm command in register_runner"
            )

    @patch.dict(os.environ, {"REGISTER_GITHUB_RUNNER_TOKEN": "fake-token"})
    @patch.object(deploy_host, 'run_cmd')
    def test_rm_and_config_sh_in_same_bash_command(self, mock_run_cmd):
        """rm and config.sh must be in a single bash -c (atomic, no gap)"""
        mock_run_cmd.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        runner = self.deployer.runners[0]
        self.deployer.register_runner(runner)

        # Find the bash -c call
        bash_calls = [
            call for call in mock_run_cmd.call_args_list
            if len(call[0]) > 0 and len(call[0][0]) > 0
            and "bash" in call[0][0] and "-c" in call[0][0]
        ]
        # Extract the shell command string (last arg of bash -c)
        for call in mock_run_cmd.call_args_list:
            args = call[0][0] if call[0] else []
            if isinstance(args, list) and "bash" in args and "-c" in args:
                c_idx = args.index("-c")
                if c_idx + 1 < len(args):
                    shell_cmd = args[c_idx + 1]
                    if "rm -f" in shell_cmd and "config.sh" in shell_cmd:
                        # Both rm and config.sh are in the same shell command
                        rm_pos = shell_cmd.index("rm -f")
                        config_pos = shell_cmd.index("config.sh")
                        self.assertLess(
                            rm_pos, config_pos,
                            "rm must run before config.sh in the shell command"
                        )
                        return
        self.fail("Could not find a bash -c command containing both rm and config.sh")

    @patch.dict(os.environ, {"REGISTER_GITHUB_RUNNER_TOKEN": "fake-token"})
    @patch.object(deploy_host, 'run_cmd')
    def test_skip_registration_when_labels_match(self, mock_run_cmd):
        """Runner with matching labels should not be re-registered"""
        runner = self.deployer.runners[0]
        expected_labels = runner.labels

        # sudo cat .labels returns matching labels
        mock_run_cmd.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=expected_labels, stderr=""
        )

        self.deployer.register_runner(runner)

        # Should only have the single sudo cat call — no config.sh
        calls_with_config_sh = [
            c for c in mock_run_cmd.call_args_list
            if "config.sh" in str(c)
        ]
        self.assertEqual(
            len(calls_with_config_sh), 0,
            "config.sh should not run when labels already match"
        )

    @patch.dict(os.environ, {"REGISTER_GITHUB_RUNNER_TOKEN": "fake-token"})
    @patch.object(deploy_host, 'run_cmd')
    def test_reconfigures_when_labels_differ(self, mock_run_cmd):
        """Runner with different labels triggers reconfiguration"""
        runner = self.deployer.runners[0]

        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            # sudo cat .labels returns stale labels
            if "cat" in cmd_str and ".labels" in cmd_str:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="old-labels", stderr=""
                )
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        mock_run_cmd.side_effect = side_effect

        self.deployer.register_runner(runner)

        # config.sh should have been called (in the bash -c command)
        config_calls = [
            c for c in mock_run_cmd.call_args_list
            if "config.sh" in str(c) and "remove" not in str(c)
            and "--url" in str(c)
        ]
        self.assertGreater(
            len(config_calls), 0,
            "config.sh registration should run when labels differ"
        )

    @patch.dict(os.environ, {}, clear=False)
    @patch.object(deploy_host, 'run_cmd')
    def test_skips_registration_without_token(self, mock_run_cmd):
        """Missing REGISTER_GITHUB_RUNNER_TOKEN skips registration gracefully"""
        os.environ.pop("REGISTER_GITHUB_RUNNER_TOKEN", None)
        runner = self.deployer.runners[0]
        # Should not raise, should not call run_cmd
        self.deployer.register_runner(runner)
        # No run_cmd calls — registration was skipped entirely
        self.assertEqual(mock_run_cmd.call_count, 0)


class TestUnconfigureRunnerIdempotency(unittest.TestCase):
    """Test _unconfigure_runner is safe to call multiple times"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = Path(self.temp_dir) / "test-config.yml"
        cfg = {
            'github': {'org': 'test-org', 'prefix': 'test', 'scope': 'org'},
            'host': {
                'runner_base': '/srv/gha',
                'docker_socket': '/var/run/docker.sock',
                'docker_user_uid': 1003,
                'docker_user_gid': 1003,
                'label': 'test-host',
            },
            'cache': {'base_dir': '/srv/gha-cache', 'permissions': '755'},
            'runners': ['cpu-small-1'],
            'sizes': {'small': {'cpus': 2.0, 'mem_limit': '4g'}},
            'runner': {'version': '2.321.0', 'arch': 'linux-x64'},
        }
        with open(self.config_file, 'w') as f:
            yaml.dump(cfg, f)
        self.deployer = HostDeployer(config_path=str(self.config_file))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch.object(deploy_host, 'run_cmd')
    def test_unconfigure_stops_service_first(self, mock_run_cmd):
        """Service must be stopped before config.sh remove runs"""
        mock_run_cmd.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        runner = self.deployer.runners[0]
        self.deployer._unconfigure_runner(runner, "fake-token")

        calls = mock_run_cmd.call_args_list
        # First call should be systemctl stop
        first_cmd = calls[0][0][0]
        self.assertIn("systemctl", first_cmd)
        self.assertIn("stop", first_cmd)

    @patch.object(deploy_host, 'run_cmd')
    def test_unconfigure_survives_service_stop_failure(self, mock_run_cmd):
        """_unconfigure_runner must not crash if systemctl stop fails"""
        mock_run_cmd.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="unit not found"
        )
        runner = self.deployer.runners[0]
        # Should not raise
        self.deployer._unconfigure_runner(runner, "fake-token")

    @patch.object(deploy_host, 'run_cmd')
    def test_unconfigure_survives_config_sh_remove_failure(self, mock_run_cmd):
        """_unconfigure_runner must not crash if config.sh remove fails (e.g. 404)"""
        mock_run_cmd.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="404 Not Found"
        )
        runner = self.deployer.runners[0]
        # Should not raise
        self.deployer._unconfigure_runner(runner, "fake-token")

    @patch.object(deploy_host, 'run_cmd')
    def test_unconfigure_survives_config_sh_exception(self, mock_run_cmd):
        """_unconfigure_runner must not crash on unexpected exceptions"""
        call_count = [0]

        def side_effect(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # systemctl stop: ok
                return subprocess.CompletedProcess(args=cmd, returncode=0)
            # config.sh remove: unexpected error
            raise OSError("no such file")

        mock_run_cmd.side_effect = side_effect
        runner = self.deployer.runners[0]
        # Should not raise — exception is caught
        self.deployer._unconfigure_runner(runner, "fake-token")


class TestUpgradePreservesConfigFiles(unittest.TestCase):
    """Verify upgrade tar commands exclude ALL runner config files"""

    def test_upgrade_tar_excludes_all_config_files(self):
        """Every RUNNER_CONFIG_FILES entry must be excluded from tar during upgrade"""
        # Read the source and find the tar_excludes construction
        source = Path(__file__).parent.parent / "deploy-host.py"
        source_text = source.read_text()

        # The upgrade method builds tar_excludes from RUNNER_CONFIG_FILES.
        # Verify by checking the constant is referenced in upgrade_runners.
        self.assertIn("RUNNER_CONFIG_FILES", source_text)

        # Also verify the constant is used to build tar excludes (not hardcoded)
        # by checking that 'tar_excludes' is built from RUNNER_CONFIG_FILES
        self.assertIn("tar_excludes", source_text)
        # The line should reference RUNNER_CONFIG_FILES
        lines = source_text.split('\n')
        tar_exclude_lines = [
            l for l in lines if 'tar_excludes' in l and 'RUNNER_CONFIG_FILES' in l
        ]
        self.assertTrue(
            len(tar_exclude_lines) > 0,
            "tar_excludes must be built from RUNNER_CONFIG_FILES constant"
        )

    def test_upgrade_preserves_work_directory(self):
        """_work directory must always be excluded from tar operations"""
        source = Path(__file__).parent.parent / "deploy-host.py"
        source_text = source.read_text()
        # _work must be excluded (it contains job data)
        self.assertIn("--exclude=_work", source_text)

    def test_config_files_not_hardcoded_in_upgrade(self):
        """Upgrade should not hardcode .runner — it should use the constant"""
        source = Path(__file__).parent.parent / "deploy-host.py"
        source_text = source.read_text()

        # Find the upgrade_runners method
        in_upgrade = False
        hardcoded_excludes = []
        for line in source_text.split('\n'):
            if 'def upgrade_runners' in line:
                in_upgrade = True
            elif in_upgrade and line.strip().startswith('def '):
                break
            elif in_upgrade and '--exclude=.runner' in line:
                # This would be a hardcoded exclude — should use the constant
                hardcoded_excludes.append(line.strip())

        self.assertEqual(
            hardcoded_excludes, [],
            f"Found hardcoded --exclude=.runner in upgrade_runners: {hardcoded_excludes}"
        )


class TestConfigFileConsistency(unittest.TestCase):
    """Ensure config file handling is consistent across all flows"""

    def test_register_and_upgrade_use_same_constant(self):
        """Both register_runner and upgrade_runners must reference RUNNER_CONFIG_FILES"""
        source = Path(__file__).parent.parent / "deploy-host.py"
        source_text = source.read_text()

        # Find methods that reference RUNNER_CONFIG_FILES
        methods_using_constant = set()
        current_method = None
        for line in source_text.split('\n'):
            stripped = line.strip()
            if stripped.startswith('def '):
                current_method = stripped.split('(')[0].replace('def ', '')
            if 'RUNNER_CONFIG_FILES' in line and current_method:
                methods_using_constant.add(current_method)

        # Both register_runner and upgrade_runners must use the constant
        self.assertIn('register_runner', methods_using_constant,
                       "register_runner must use RUNNER_CONFIG_FILES")
        self.assertIn('upgrade_runners', methods_using_constant,
                       "upgrade_runners must use RUNNER_CONFIG_FILES")

    def test_runner_migrated_always_paired_with_runner(self):
        """Wherever .runner is deleted, .runner_migrated must also be deleted"""
        # This is guaranteed by using the RUNNER_CONFIG_FILES constant,
        # but verify it's true in the actual rm commands
        source = Path(__file__).parent.parent / "deploy-host.py"
        source_text = source.read_text()

        lines = source_text.split('\n')
        for i, line in enumerate(lines):
            if 'rm -f' in line and '.runner' in line and 'RUNNER_CONFIG_FILES' not in line:
                # If there's a hardcoded rm that mentions .runner, it must
                # also mention .runner_migrated (or be a manual cleanup hint)
                if '.runner_migrated' not in line and 'Try manually' not in line:
                    self.fail(
                        f"Line {i+1} deletes .runner without .runner_migrated: "
                        f"{line.strip()}"
                    )


if __name__ == '__main__':
    unittest.main()
