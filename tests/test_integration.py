#!/usr/bin/env python3
"""
Integration tests for gha-runnerd deployment script.

These tests validate:
- Configuration parsing and validation
- Runner name parsing and label generation
- Command-line argument handling
"""

import unittest
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


if __name__ == '__main__':
    unittest.main()
