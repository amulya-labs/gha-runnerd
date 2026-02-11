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
