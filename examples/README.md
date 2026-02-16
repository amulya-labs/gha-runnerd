# Examples

This directory contains example configurations and workflows to help you get started with gha-runnerd.

## Workflow Examples

Example GitHub Actions workflows demonstrating best practices:

- **[python.yml](workflows/python.yml)** - Python CI with linting, testing, and integration tests
- **[nodejs.yml](workflows/nodejs.yml)** - Node.js CI with linting, testing, and builds
- **[rust.yml](workflows/rust.yml)** - Rust CI with clippy, tests, and release builds
- **[docker-build.yml](workflows/docker-build.yml)** - Docker image builds using specialized docker runners

### Key Patterns

All workflow examples demonstrate:

1. **Always use containers** - Ensures consistent, reproducible environments
2. **Local caching with [gha-opencache](https://github.com/amulya-labs/gha-opencache)** - Sub-second cache restores
3. **Size-appropriate runners** - Match runner size to workload (xs→small→medium→large)
4. **Proper cache keys** - Use lock files for dependency caching

### Runner Label Usage

```yaml
# Lightweight tasks (linting, quick checks)
runs-on: [self-hosted, linux, cpu, xs, generic]

# Unit tests, small builds
runs-on: [self-hosted, linux, cpu, small, generic]

# Integration tests, medium builds
runs-on: [self-hosted, linux, cpu, medium, generic]

# Large builds, compilation
runs-on: [self-hosted, linux, cpu, large, generic]

# Docker builds (no container wrapping)
runs-on: [self-hosted, linux, cpu, medium, docker]

# GPU workloads
runs-on: [self-hosted, linux, gpu, max, generic]
```

## Configuration Examples

Example runner deployment configurations:

- **[minimal.yml](configs/minimal.yml)** - Minimal setup for personal projects (2 runners)
- **[production.yml](configs/production.yml)** - Full production setup with multiple runner types
- **[gpu-enabled.yml](configs/gpu-enabled.yml)** - Configuration with GPU support for ML/AI workloads

### Quick Start

1. Copy an example config:
   ```bash
   cp examples/configs/minimal.yml config.yml
   ```

2. Edit the configuration:
   ```bash
   vim config.yml  # Update org, prefix, and host settings
   ```

3. Deploy:
   ```bash
   ./deploy-host.py --validate  # Validate first
   ./deploy-host.py             # Deploy
   ```

### Configuration Tips

- **Start small** - Begin with `minimal.yml` and add runners as needed
- **Use meaningful prefixes** - `dev`, `staging`, `prod` help identify environments
- **Size runners appropriately** - Don't over-provision; start with small/medium
- **Enable GPU only if needed** - Requires nvidia-docker2 and proper drivers

## Using Example Configurations

The example configs are ready to use with minimal changes:

1. **Choose an example** that fits your needs (minimal, production, or gpu-enabled)
2. **Copy it** to your config file:
   ```bash
   cp examples/configs/minimal.yml config.yml
   ```
3. **Edit organization details**:
   ```bash
   vim config.yml  # Update 'org' and 'prefix' values
   ```
4. **Validate and deploy**:
   ```bash
   ./deploy-host.py --validate
   ./deploy-host.py
   ```

## Testing Examples Locally

Before deploying to production, test with example configurations:

```bash
# Validate an example config
./deploy-host.py --validate --config examples/configs/minimal.yml

# Dry-run to preview deployment
./deploy-host.py --dry-run --config examples/configs/minimal.yml

# Deploy using example config (for testing)
./deploy-host.py --config examples/configs/minimal.yml
```

**Note:** The `--config` flag allows you to use different configuration files for different environments or hosts.

## Questions?

See the main [README.md](../README.md) for complete documentation.
