# gha-runnerd

**Deploy self-hosted GitHub Actions runners in 5 minutes.** Get sub-second caching, full container support, and predictable costs.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/amulya-labs/gha-runnerd/workflows/CI/badge.svg)](https://github.com/amulya-labs/gha-runnerd/actions)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Code of Conduct](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](CODE_OF_CONDUCT.md)

---

## What is this?

**gha-runnerd** (GitHub Actions Runner Daemon) is a deployment tool that sets up self-hosted CI/CD runners on your Linux servers. Instead of paying GitHub per-minute for hosted runners, you run builds on your own hardware with better performance and lower costs.

**For decision-makers:** Reduce CI/CD costs by 60-80% while getting 10-60x faster dependency caching. Your code stays on your infrastructure.

**For engineers:** A single Python script that configures systemd services, handles GitHub registration, and manages the full runner lifecycle. No Kubernetes required.

---

## Quick Start (5 minutes)

```bash
# 1. Install prerequisites
curl -fsSL https://get.docker.com | sudo sh
sudo apt install gh
pip install -r requirements.txt

# 2. Authenticate with GitHub
gh auth login

# 3. Configure
cp config.example.yml config.yml
vim config.yml  # Set your org and runners

# 4. Deploy
./deploy-host.py --validate  # Check config
./deploy-host.py             # Deploy runners

# 5. Use in workflows
# runs-on: [self-hosted, linux, cpu, small, generic]
# container: { image: python:3.11 }
```

**Next steps:**
- [Detailed setup guide](#installation) | [Migration from other setups](docs/MIGRATION.md) | [Security considerations](SECURITY.md)

---

## Why gha-runnerd?

| Feature | gha-runnerd | GitHub-hosted | actions-runner-controller |
|---------|-------------|---------------|---------------------------|
| **Cache restore time** | Sub-second | 10-60 seconds | Cluster-dependent |
| **Setup time** | 5 minutes | N/A | Hours (Kubernetes) |
| **Cost model** | Fixed (hardware) | Per-minute | Fixed (cluster) |
| **`jobs.container` support** | Full | Full | Full |
| **GPU support** | Yes | Limited | Yes |
| **Kubernetes required** | No | N/A | Yes |

### Key benefits

- **60x faster caching** - Local disk cache restores in milliseconds, not minutes
- **Zero nested container issues** - Host-based runners fully support `jobs.container` with no Docker-in-Docker complexity
- **Predictable costs** - Pay for hardware once, not per-minute
- **Container-first workflows** - Use `python:3.11`, `node:20`, `rust:latest` directly without host dependencies
- **Full control** - Custom hardware, GPUs, compliance requirements, air-gapped environments

### Who should use this?

- Teams running **50+ builds/day** where caching and costs matter
- Organizations with **compliance or data residency** requirements
- Projects needing **GPU or specialized hardware**
- Anyone who wants **simple self-hosted runners without Kubernetes**

---

## How it works

```
┌─────────────────┐     ┌──────────────────────────────────────────┐
│  GitHub.com     │     │  Your Linux Server                       │
│                 │     │                                          │
│  ┌───────────┐  │     │  ┌──────────────────────────────────┐   │
│  │ Workflow  │──┼────▶│  │ systemd service (gha-runner)     │   │
│  │ triggers  │  │     │  │                                  │   │
│  └───────────┘  │     │  │  ┌─────────────────────────────┐ │   │
│                 │     │  │  │ Job Container (python:3.11) │ │   │
│                 │     │  │  │  - checkout                 │ │   │
│                 │     │  │  │  - gha-opencache (restore)  │ │   │
│                 │     │  │  │  - pip install              │ │   │
│                 │     │  │  │  - pytest                   │ │   │
│                 │     │  │  └─────────────────────────────┘ │   │
│                 │     │  └──────────────────────────────────┘   │
│                 │     │                                          │
│                 │     │  /srv/gha-cache/ (shared, sub-second)   │
└─────────────────┘     └──────────────────────────────────────────┘
```

1. **Runners run on host** as systemd services (not containers)
2. **Jobs run in containers** using `jobs.container` for isolation
3. **Cache is local** via [gha-opencache](https://github.com/amulya-labs/gha-opencache) - sub-second restores
4. **No nested Docker** - full compatibility with all GitHub Actions

---

## Prerequisites

**System Requirements:**
- **OS**: Ubuntu 20.04+ or Debian 11+ (systemd-based Linux)
- **Hardware**:
  - Minimum: 4 CPU cores, 8GB RAM (for deployment tool + 1-2 runners)
  - Recommended: 8+ CPU cores, 16GB+ RAM (for multiple concurrent runners)
  - Disk: 20GB+ free space (more for caching dependencies)
- **Access**: Root/sudo privileges required for systemd service management
- **Network**: Internet access to download runner binaries and container images

**Required Tools:**
```bash
# 1. Docker (20.10+)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# 2. Python 3.8+ with PyYAML
pip install -r requirements.txt

# 3. GitHub CLI (gh) - Required for authentication
# See: https://github.com/cli/cli/blob/trunk/docs/install_linux.md
# Ubuntu/Debian example:
sudo apt install gh

# 4. Authenticate with GitHub (required for fetching runner registration tokens)
gh auth login
```

**Important Notes:**
- The script requires `gh` CLI authentication to fetch runner registration tokens automatically
- Alternatively, manually set `REGISTER_GITHUB_RUNNER_TOKEN` environment variable
- You need organization admin permissions to register runners
- The deployment script will create required directories and configuration (with ownership set to your configured runner user), but it does **not** create the Unix user itself; you must create the runner user (e.g., `ci-docker`) beforehand

---

## Installation

```bash
# Clone the repository
git clone https://github.com/amulya-labs/gha-runnerd.git
cd gha-runnerd

# Install Python dependencies
pip install -r requirements.txt

# Copy and edit configuration
cp config.example.yml config.yml
# Edit config.yml with your organization details
```

---

## Deploy

```bash
# Validate configuration first (recommended)
./deploy-host.py --validate

# Preview what will be deployed (dry-run)
./deploy-host.py --dry-run

# Deploy runners (will prompt for sudo password when needed)
./deploy-host.py

# Verify deployment
sudo systemctl status 'gha-*'
```

**Note:**
- The script automatically fetches the registration token using `gh` CLI (run `gh auth login` first if not authenticated)
- You'll be prompted for your sudo password with clear explanations of what action requires elevated privileges
- No need to run the entire script with sudo!

**Example sudo prompts you'll see:**
```
[INFO   ] 🔒 Requesting sudo access for: creating runner base directory /srv/gha
[sudo] password for user:

[INFO   ] 🔒 Requesting sudo access for: installing sudoers configuration for workspace cleanup
[INFO   ] 🔒 Requesting sudo access for: enabling systemd service gha-my-linux-cpu-small-1
[INFO   ] 🔒 Requesting sudo access for: starting runner service gha-my-linux-cpu-small-1
```

---

## Configuration

Edit `config.yml`:

```yaml
github:
  org: "your-org"
  prefix: "my"

runners:
  - "cpu-small-1"          # Generic runner for containerized jobs
  - "cpu-medium-1"         # Generic runner for containerized jobs
  - "cpu-medium-docker-1"  # Specialized for Docker builds (no container)
  - "gpu-max-1"            # GPU runner

sizes:
  small:
    cpus: 2.0
    mem_limit: "4g"
  medium:
    cpus: 6.0
    mem_limit: "16g"
```

### Deploy

```bash
./deploy-host.py
```

> **Note:**
> - You'll be prompted for your sudo password when needed (to create systemd services, directories, etc.)
> - Script automatically fetches registration token via `gh` CLI if not already set
> - Use `--dry-run` to preview changes without applying them
> - Use `--verbose` for detailed logging

### Configuration Reference

All configuration options with their defaults:

```yaml
# GitHub organization settings (REQUIRED)
github:
  org: "your-org"      # GitHub organization name
  prefix: "my"         # Prefix for service/runner names

# Host environment (REQUIRED)
host:
  label: "my-host"              # Host label added to all runners
  runner_base: "/srv/gha"       # Base directory for runners
  docker_socket: "/var/run/docker.sock"
  docker_user_uid: 1003         # UID for runner user
  docker_user_gid: 1003         # GID for runner user

# Cache configuration (OPTIONAL - defaults shown)
cache:
  base_dir: "/srv/gha-cache"    # Shared cache for gha-opencache
  permissions: "755"            # Cache directory permissions

# Runner binary settings (REQUIRED)
runner:
  version: "2.329.0"            # GitHub Actions runner version
  arch: "linux-x64"             # Architecture
  # Optional: Override download URL template
  # download_url_template: "https://github.com/actions/runner/releases/download/v{version}/actions-runner-{arch}-{version}.tar.gz"

# Systemd service settings (OPTIONAL - defaults shown)
systemd:
  restart_policy: "always"      # Restart policy (always, on-failure, no)
  restart_sec: 10               # Seconds to wait before restart

# Sudoers configuration (OPTIONAL - defaults shown)
sudoers:
  path: "/etc/sudoers.d/gha-runner-cleanup"  # Path to sudoers file

# Runners to deploy (REQUIRED)
runners:
  - "cpu-small-1"
  - "cpu-medium-1"

# Size definitions (REQUIRED)
sizes:
  xs:
    cpus: 1.0
    mem_limit: "2g"
    pids_limit: 1024
  small:
    cpus: 2.0
    mem_limit: "4g"
    pids_limit: 2048
  medium:
    cpus: 6.0
    mem_limit: "16g"
    pids_limit: 4096

# Optional: GitHub API label sync
github_api:
  enforce_labels: true          # Sync labels via API (requires gh CLI)
```

**Note:** All optional sections will use sensible defaults if not specified. See `config.example.yml` for a complete example.

---

## Writing Workflows

### Runner Label Format

**Naming Convention:** `{type}-{size}-[{category}]-{number}`

- `type` - `cpu` or `gpu`
- `size` - `xs`, `small`, `medium`, `large`, or `max`
- `category` - Optional specialization (e.g., `docker`, `bazel`)
- `number` - Instance number (1, 2, 3, ...)

**Labels generated:** All components except the number (adds `generic` if no category)

Examples:
- `cpu-medium-1` → `[self-hosted, linux, my-host, cpu, medium, generic]`
- `cpu-medium-docker-1` → `[self-hosted, linux, my-host, cpu, medium, docker]`
- `gpu-large-cuda-1` → `[self-hosted, linux, my-host, gpu, large, cuda]`

**Available sizes:**
- `xs` - 1 CPU, 2GB RAM (lightweight tasks)
- `small` - 2 CPUs, 4GB RAM (tests, linting)
- `medium` - 6 CPUs, 16GB RAM (integration tests, builds)
- `large` - 12 CPUs, 32GB RAM (heavy builds)
- `max` - Unlimited resources (special workloads)

**Examples:**
```yaml
runs-on: [self-hosted, linux, cpu, xs, generic]      # Lightweight tasks
runs-on: [self-hosted, linux, cpu, small, generic]   # Unit tests, linting
runs-on: [self-hosted, linux, cpu, medium, generic]  # Integration tests
runs-on: [self-hosted, linux, gpu, max, generic]     # GPU workloads
```

### Using Containers

**Always use containers** for consistent environments:

```yaml
# Python
jobs:
  test:
    runs-on: [self-hosted, linux, cpu, small, generic]
    container:
      image: python:3.11
    steps:
      - uses: actions/checkout@v5
      - run: pip install -r requirements.txt
      - run: pytest

# Node.js
  build:
    runs-on: [self-hosted, linux, cpu, medium, generic]
    container:
      image: node:20
    steps:
      - uses: actions/checkout@v5
      - run: npm ci
      - run: npm run build

# Rust
  compile:
    runs-on: [self-hosted, linux, cpu, large, generic]
    container:
      image: rust:1.75
    steps:
      - uses: actions/checkout@v5
      - run: cargo build --release
```

### When to Use Specialized Runners

Use specialized runners (with category) for tasks that **cannot run in containers**:

```yaml
# Docker builds - needs host Docker access
jobs:
  build-image:
    runs-on: [self-hosted, linux, cpu, medium, docker]  # Note: 'docker' category
    steps:
      - uses: actions/checkout@v5
      - name: Build Docker image
        run: docker build -t myimage .
      - name: Push to registry
        run: docker push myimage

# Bazel builds - benefits from persistent host cache
  bazel-build:
    runs-on: [self-hosted, linux, cpu, large, bazel]  # Note: 'bazel' category
    steps:
      - uses: actions/checkout@v5
      - name: Build with Bazel
        run: bazel build //...
```

To add a specialized runner, add it to `config.yml`:
```yaml
runners:
  - "cpu-medium-1"         # Generic
  - "cpu-medium-docker-1"  # Docker builds
  - "cpu-large-bazel-1"    # Bazel builds
```

### Using Service Containers

**Add databases and services** to your jobs:

```yaml
jobs:
  test:
    runs-on: [self-hosted, linux, cpu, medium, generic]
    container:
      image: python:3.11
    services:
      # PostgreSQL
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s

      # Redis
      redis:
        image: redis:7
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s

    steps:
      - uses: actions/checkout@v5
      - run: pytest
        env:
          DATABASE_URL: postgresql://postgres:postgres@postgres:5432/db
          REDIS_URL: redis://redis:6379
```

### Caching Dependencies

**Use [`gha-opencache`](https://github.com/amulya-labs/gha-opencache)** for fast local caching. It's a drop-in replacement for `actions/cache` with pluggable backends (local disk, S3, GCS).

```yaml
# Python (Poetry)
- name: Cache Poetry dependencies
  id: cache-poetry
  uses: amulya-labs/gha-opencache@v3
  with:
    path: .venv
    key: poetry-${{ runner.os }}-${{ hashFiles('**/poetry.lock') }}
    restore-keys: poetry-${{ runner.os }}-

- name: Warn on cache miss
  if: steps.cache-poetry.outputs.cache-hit != 'true'
  run: echo "::warning::Poetry cache miss. Installing from scratch."

# Node.js (cache npm's cache directory when using npm ci)
- uses: amulya-labs/gha-opencache@v3
  with:
    path: ~/.npm
    key: npm-${{ runner.os }}-${{ hashFiles('**/package-lock.json') }}
    restore-keys: npm-${{ runner.os }}-

# Rust
- uses: amulya-labs/gha-opencache@v3
  with:
    path: |
      ~/.cargo/registry
      ~/.cargo/git
      target
    key: cargo-${{ runner.os }}-${{ hashFiles('**/Cargo.lock') }}
    restore-keys: cargo-${{ runner.os }}-
```

**Why gha-opencache + gha-runnerd?**

| Setup | Cache restore time | Where cache lives |
|-------|-------------------|-------------------|
| GitHub-hosted + `actions/cache` | 10-60 seconds | GitHub's servers |
| Self-hosted + `actions/cache` | 10-60 seconds | GitHub's servers (network bottleneck) |
| **gha-runnerd + gha-opencache** | **Sub-second** | **Local disk** |

The combination eliminates network round-trips entirely. Caches are stored on the runner's local disk (`/srv/gha-cache/`) and shared across all runners on the same host.

**Best practices:**
- Use `restore-keys` for partial matching (falls back to older cache if exact match fails)
- Add `${{ runner.os }}` to cache keys to avoid cross-platform issues
- Add a "Warn on cache miss" step to make cache misses visible in logs

**Common cache paths:**
- Python: `.venv` (with Poetry's `virtualenvs-in-project: true`)
- Node: `~/.npm` (when using `npm ci`) or `node_modules` (when using `npm install`)
- Rust: `~/.cargo/registry`, `~/.cargo/git`, and `target/`
- Go: `~/go/pkg/mod` or `~/.cache/go-build`
- Maven: `~/.m2/repository`
- Gradle: `~/.gradle/caches`

> **Note:** You can also use `corca-ai/local-cache@v2` with `base: /srv/gha-cache` as an alternative.

---

## Deployment Options

The deployment script supports several flags for different use cases:

### Validate Configuration

Check your configuration for errors before deploying:

```bash
./deploy-host.py --validate
```

This validates:
- Required sections are present
- Runner names are valid (format: `{type}-{size}-[{category}]-{number}`)
- Size definitions exist
- No placeholder values (`your-org`)
- No duplicate runner names

### Dry-Run Mode

Preview what would be deployed without making any changes:

```bash
./deploy-host.py --dry-run
```

Dry-run shows:
- Which directories would be created
- Which runners would be registered
- What systemd services would be created
- Resource limits for each runner

Perfect for testing configuration changes before applying them.

### List Deployed Runners

View all currently deployed runners and their status:

```bash
./deploy-host.py --list
```

Shows:
- Runner names and service status
- Resource limits (CPU, memory)
- Whether services are active/inactive
- Systemd service names

### Remove a Runner

Remove a specific runner from the system:

```bash
./deploy-host.py --remove cpu-small-1
```

This will:
- Stop and disable the systemd service
- Remove the runner directory
- Clean up service files

**Note:** The runner will auto-remove from GitHub after 30 days offline.

### Upgrade Runner Binaries

Upgrade all deployed runners to a new version:

```bash
# 1. Update version in config.yml
vim config.yml  # Change runner.version to new version

# 2. Run upgrade
./deploy-host.py --upgrade
```

The upgrade process:
- Downloads new runner binaries
- Stops each runner service
- Replaces the runner binary
- Restarts the service
- Preserves runner registration (no re-registration needed)

**Important:** Always test upgrades on a non-production runner first.

### Custom Configuration File

Use a different configuration file:

```bash
./deploy-host.py --config custom-config.yml
```

Useful for:
- Managing multiple environments (dev, staging, prod)
- Testing configuration changes
- Per-host configurations

### Verbose Output

Enable detailed logging for troubleshooting:

```bash
./deploy-host.py --verbose
```

Verbose mode shows:
- Every command being executed
- Command execution times
- Environment details
- Service file contents (in dry-run)

### Combining Flags

You can combine multiple flags:

```bash
# Validate with verbose output
./deploy-host.py --validate --verbose

# Dry-run with verbose output to see all details
./deploy-host.py --dry-run --verbose

# Deploy with verbose logging and custom config
./deploy-host.py --config prod.yml --verbose

# List runners with verbose output
./deploy-host.py --list --verbose
```

---

## Managing Runners

### Adding Runners

**Add new runners** to your infrastructure:

1. Edit `config.yml` to add runner names:
   ```yaml
   runners:
     - "cpu-small-1"
     - "cpu-medium-1"
     - "cpu-large-1"  # ← Add new runner
   ```

2. Deploy (creates systemd service and registers with GitHub):
   ```bash
   ./deploy-host.py
   ```

**What happens:**
- Creates `/srv/gha/{prefix}-linux-{runner-name}/`
- Creates systemd service `gha-{prefix}-linux-{runner-name}`
- Registers runner with GitHub
- Starts the service

### Removing Runners

**Remove runners** from your infrastructure:

1. Edit `config.yml` to remove runner names:
   ```yaml
   runners:
     - "cpu-small-1"
     - "cpu-medium-1"
     # - "cpu-large-1"  # ← Removed
   ```

2. Re-deploy (automatically cleans up removed runners):
   ```bash
   ./deploy-host.py
   ```

**What happens:**
- Detects runners in systemd but not in config
- Stops and disables removed services
- Removes service files and runner directories
- Continues with deployment of remaining runners

**Note:** Runners will auto-remove from GitHub after 30 days offline

### Modifying Runner Resources

**Change CPU/memory limits** for existing runners:

1. Edit `config.yml` to update size limits:
   ```yaml
   sizes:
     medium:
       cpus: 8.0          # Changed from 6.0
       mem_limit: "20g"   # Changed from 16g
       pids_limit: 4096
   ```

2. Re-deploy to apply changes:
   ```bash
   ./deploy-host.py
   ```

**What happens:**
- Updates systemd service files with new limits
- Restarts affected runners
- No re-registration needed

### Upgrading Runner Binaries

**Update runners to a new GitHub Actions runner version:**

1. Check current runner version:
   ```bash
   grep "version:" config.yml
   ```

2. Update version in `config.yml`:
   ```yaml
   runner:
     version: "2.329.0"  # Update to new version
     arch: "linux-x64"
   ```

3. Preview the upgrade:
   ```bash
   ./deploy-host.py --upgrade --dry-run
   ```

4. Perform the upgrade:
   ```bash
   ./deploy-host.py --upgrade
   ```

**What happens:**
- Downloads new runner binaries
- Stops each runner service gracefully (waits for current job to complete)
- Replaces runner binaries
- Restarts services
- Preserves runner registration and configuration

**Best practices:**
- **Test first**: Upgrade one non-critical runner before upgrading all
- **Check release notes**: Review [GitHub Actions Runner releases](https://github.com/actions/runner/releases) for breaking changes
- **Monitor workflows**: Watch for any issues after upgrade
- **Backup**: The old runner binary is preserved as `run.sh.old` during upgrade
- **Timing**: Upgrade during low-activity periods when possible

**Rollback if needed:**
If the new version causes issues, you can rollback:
```bash
# Stop the service
sudo systemctl stop gha-my-linux-cpu-small-1

# Restore old binary
cd /srv/gha/my-linux-cpu-small-1
mv run.sh.old run.sh

# Update config.yml to old version
# Then restart
sudo systemctl start gha-my-linux-cpu-small-1
```

### Common Commands

```bash
# List all runner services
systemctl list-units 'gha-*'

# List all runner services (including inactive)
systemctl list-units 'gha-*' --all

# View all runners status
sudo systemctl status 'gha-*'

# View logs (follow)
sudo journalctl -u gha-{prefix}-linux-cpu-small-1 -f

# Restart a runner
sudo systemctl restart gha-{prefix}-linux-cpu-small-1

# Check shared cache size
du -sh /srv/gha-cache/

# List cached items
ls -la /srv/gha-cache/
```

---

<details>
<summary><h2>Appendix</h2></summary>

## Architecture

- **Host-based runners** execute as systemd services (not containers)
- Each runner runs as `ci-docker` user (UID 1003)
- Runner homes: `/srv/gha/{runner-name}/`
- Resource limits via systemd (CPUQuota, MemoryLimit, TasksMax)
- Workflow execution: `Host runner → Job container → Steps`

**Why host-based?**
- Fixes `jobs.container` + Node-based actions compatibility
- Eliminates nested Docker issues
- Simpler debugging and management

---

## Naming Convention

**Format:** `{type}-{size}-{number}`

**Types:**
- `cpu` - Generic CPU runner
- `gpu` - GPU-enabled runner (requires NVIDIA drivers)

**Sizes:** `xs`, `small`, `medium`, `large`, `max`

**Examples:**
- `cpu-small-1` → Labels: `self-hosted,linux,my-host,cpu,small,generic`
- `cpu-medium-2` → Labels: `self-hosted,linux,my-host,cpu,medium,generic`
- `gpu-max-1` → Labels: `self-hosted,linux,my-host,gpu,max,generic`

**Auto-generated:**
- Service name: `gha-{prefix}-linux-{type}-{size}-{number}`
- Registered name: `{prefix}-linux-{type}-{size}-{number}`

---

## Resource Limits

Configured in `config.yml`, enforced via systemd:

```yaml
sizes:
  small:
    cpus: 2.0         # → CPUQuota=200%
    mem_limit: "4g"   # → MemoryLimit=4g
    pids_limit: 2048  # → TasksMax=2048
  medium:
    cpus: 6.0
    mem_limit: "16g"
    pids_limit: 4096
  large:
    cpus: 12.0
    mem_limit: "32g"
    pids_limit: 8192
  max:
    cpus: null        # No limits
    mem_limit: null
    pids_limit: null
```

---

## Container Best Practices

### Image Selection

**Use official images when possible:**
- Rust: `rust:1.75`, `rust:1.75-slim`
- Node: `node:20`, `node:20-alpine`
- Python: `python:3.12`, `python:3.12-slim`
- Go: `golang:1.21`
- Java: `eclipse-temurin:17`

**Specify exact versions for reproducibility:**
```yaml
container:
  image: node:20.11.0  # ← Exact version
```

### Custom Images

**When to build custom images:**
- Need specific pre-installed tools
- Combine multiple toolchains
- Optimize layer caching
- Corporate firewall/registry requirements

**Example Dockerfile:**
```dockerfile
FROM rust:1.75

# Install additional tools
RUN cargo install cargo-audit cargo-deny

# Pre-download common dependencies
WORKDIR /tmp
COPY Cargo.toml Cargo.lock ./
RUN cargo fetch

WORKDIR /workspace
```

### Container Registry Options

**Public registries:**
- Docker Hub: `rust:latest`
- GitHub Container Registry: `ghcr.io/actions/rust:latest`
- Google Container Registry: `gcr.io/buildpacks/builder:latest`

**Private registry:**
```yaml
container:
  image: your-registry.com/custom-rust:v1.0
  credentials:
    username: ${{ secrets.REGISTRY_USERNAME }}
    password: ${{ secrets.REGISTRY_PASSWORD }}
```

---

## Advanced Caching

### Multi-Stage Caching

```yaml
- name: Cache dependencies
  uses: amulya-labs/gha-opencache@v3
  with:
    path: ~/.cargo/registry
    key: deps-${{ runner.os }}-${{ hashFiles('Cargo.lock') }}
    restore-keys: deps-${{ runner.os }}-

- name: Cache build artifacts
  uses: amulya-labs/gha-opencache@v3
  with:
    path: target
    key: build-${{ runner.os }}-${{ hashFiles('src/**/*.rs') }}
    restore-keys: build-${{ runner.os }}-
```

### Conditional Caching

```yaml
- uses: amulya-labs/gha-opencache@v3
  if: ${{ !env.ACT }}  # Skip in local testing
  with:
    path: ~/.cache
    key: cache-key
```

### Cross-Job Caching

Caches are automatically shared across jobs on the same runner.

---

## Troubleshooting

### Common Issues

#### 1. GitHub CLI Authentication Failed

**Symptom:** Error fetching registration token: "Not authenticated with gh CLI"

**Solution:**
```bash
# Authenticate with GitHub
gh auth login

# Verify authentication
gh auth status

# Re-run deployment
./deploy-host.py
```

**Root cause:** The script needs `gh` CLI access to fetch runner registration tokens.

---

#### 2. Organization Permission Denied

**Symptom:** "Insufficient permissions for the organization" when fetching token

**Solution:**
1. Verify you have **admin** permissions in the GitHub organization
2. Check organization name in `config.yml` is correct
3. Visit GitHub org settings: `https://github.com/organizations/YOUR-ORG/settings/actions/runners`
4. Ensure you can manually create runners via the UI

**Root cause:** Only organization admins can register self-hosted runners.

---

#### 3. Docker Daemon Not Running

**Symptom:** "Cannot connect to the Docker daemon"

**Solution:**
```bash
# Check Docker status
sudo systemctl status docker

# Start Docker if stopped
sudo systemctl start docker
sudo systemctl enable docker

# Verify Docker works
docker ps
```

**Root cause:** Docker service must be running for containerized workflows.

---

#### 4. Runner Service Won't Start

**Symptom:** `systemctl status gha-*` shows failed/inactive

**Solution:**
```bash
# View detailed logs (last 100 lines)
sudo journalctl -u gha-{prefix}-linux-{runner-name} -n 100

# Check for common issues:
# - Registration token expired (re-run deploy-host.py)
# - Permissions on /srv/gha incorrect (should be 1003:1003)
# - Runner binary corrupted (delete runner dir and re-deploy)

# Fix permissions
sudo chown -R 1003:1003 /srv/gha

# Re-deploy runner
./deploy-host.py
```

**Root cause:** Usually token expiration or permission issues.

---

#### 5. Runner Not Appearing in GitHub

**Symptom:** Deployment completes but runner doesn't show in GitHub org settings

**Solution:**
```bash
# 1. Check service is running
sudo systemctl status gha-*

# 2. Check runner logs for errors
sudo journalctl -u gha-{runner-name} -f

# 3. Verify network connectivity to GitHub
curl -I https://github.com

# 4. Re-run deployment with fresh token
./deploy-host.py
```

**Root cause:** Token expired, network issues, or runner failed to register.

---

#### 6. Workspace Permission Denied (EACCES)

**Symptom:** `EACCES: permission denied` during checkout

**Solution:**
```bash
# Re-deploy to install cleanup hook
./deploy-host.py

# Verify cleanup hook exists
ls -la /srv/gha/{runner-name}/cleanup-workspace.sh

# Verify sudoers entry
sudo cat /etc/sudoers.d/gha-runner-cleanup
```

**Root cause:** Docker containers run as root by default, creating files the runner user can't delete. The cleanup hook fixes workspace permissions and removes stale tool installations from `$HOME/.local` before each job.

---

#### 7. Tools Crash with "cannot open shared object file"

**Symptom:** Poetry, pip, or other tools crash with `error while loading shared libraries: libpythonX.Y.so.1.0: cannot open shared object file`

**Solution:** Re-deploy to install the updated cleanup hook:
```bash
./deploy-host.py
```

**Root cause:** When container jobs with different base images (e.g., `python:3.12` and `python:3.11`) run on the same runner, tools installed to `$HOME/.local/` persist and reference shared libraries from the previous container. The cleanup hook removes `$HOME/.local` before each job to prevent this cross-container contamination.

**Optimization:** If the ~8s reinstall overhead becomes a concern for heavier toolchains, workflows can layer explicit caching of `$HOME/.local` via `gha-opencache` with image-aware keys (e.g., `home-local-${{ matrix.container }}-${{ hashFiles('requirements.txt') }}`). The hook cleanup remains as defense-in-depth.

---

#### 8. Cache Not Working

**Symptom:** "Cache not found" in every workflow run

**Solution:**
```bash
# 1. Verify shared cache directory exists
ls -la /srv/gha-cache/
# Should show: drwxr-xr-x 1003 1003 /srv/gha-cache

# 2. Create if missing
sudo mkdir -p /srv/gha-cache
sudo chown 1003:1003 /srv/gha-cache
sudo chmod 755 /srv/gha-cache
```

**In your workflow with gha-opencache:**
```yaml
- uses: amulya-labs/gha-opencache@v3
  with:
    path: .venv
    key: poetry-${{ hashFiles('poetry.lock') }}
```

**Root cause:** Cache directory doesn't exist or has incorrect permissions.

---

#### 8. Python Dependencies Missing

**Symptom:** "ModuleNotFoundError: No module named 'yaml'"

**Solution:**
```bash
# Install Python dependencies
pip install -r requirements.txt

# Or install PyYAML directly
pip install pyyaml
```

**Root cause:** PyYAML not installed on deployment host.

---

#### 9. Port Conflicts (Rare)

**Symptom:** Service fails to start with "address already in use"

**Solution:**
```bash
# Check what's using runner ports (unlikely)
sudo netstat -tulpn | grep -E ':(8080|9091)'

# Runners don't bind ports by default
# This usually indicates a misconfigured workflow
```

**Root cause:** Workflow trying to bind to a port already in use by another runner/service.

---

#### 10. Disk Space Exhausted

**Symptom:** Workflows fail with "No space left on device"

**Solution:**
```bash
# Check disk usage
df -h /srv

# Check cache size
du -sh /srv/gha-cache/

# Clean up old caches (manual)
# CAREFUL: This deletes ALL cached dependencies
sudo rm -rf /srv/gha-cache/*

# Clean up Docker images
docker system prune -af

# Clean up old build artifacts in runner workspaces
sudo find /srv/gha -name '_work' -type d -exec du -sh {} \;
sudo rm -rf /srv/gha/*/_work/*  # CAREFUL: Deletes all workspaces
```

**Root cause:** Accumulated caches, Docker images, and build artifacts.

---

### Quick Reference

| Issue | Solution |
|-------|----------|
| PyYAML not installed | `pip install -r requirements.txt` |
| gh not authenticated | `gh auth login` |
| Permission denied on `/srv/gha` | `sudo chown -R 1003:1003 /srv/gha` |
| Workspace permission denied (EACCES) | Re-deploy to install cleanup hook |
| Tools crash with "cannot open shared object file" | Re-deploy to install updated cleanup hook |
| Service won't start | `sudo journalctl -u gha-<service> -n 100` |
| Runner not in GitHub | Check token, re-run `./deploy-host.py` |
| GPU not accessible | Install NVIDIA drivers + Container Toolkit |
| Docker permission denied | `sudo usermod -aG docker ci-docker && sudo systemctl restart 'gha-*'` |
| Container image pull fails | Check registry credentials, network |
| Cache not persisting | Verify `/srv/gha-cache` exists with ownership 1003:1003 |
| Cache always misses | Ensure `base: /srv/gha-cache` is set in workflow |
| Disk space exhausted | Clean caches, Docker images, old workspaces |

### Workspace Permission Issues

When Docker containers run as root (the default), they can create files that the runner user (`ci-docker`) cannot delete. This causes `EACCES: permission denied` errors during checkout.

**Solution:** The deploy script installs a pre-job cleanup hook that automatically fixes workspace permissions and removes stale tool installations before each job. If you see this error, re-deploy:

```bash
./deploy-host.py
```

This creates:
- `/srv/gha/{runner}/cleanup-workspace.sh` - runs before each job, fixes `_work/` ownership and removes `$HOME/.local/` to prevent cross-container tool contamination
- `/etc/sudoers.d/gha-runner-cleanup` - allows runner to `chown` workspace and `.local` directories

### Cache Not Working

If cache always misses ("Cache not found" in logs), check:

1. **Shared cache directory exists:**
   ```bash
   ls -la /srv/gha-cache/
   # Should show directory owned by ci-docker (1003:1003)
   ```

2. **Create if missing:**
   ```bash
   sudo mkdir -p /srv/gha-cache
   sudo chown 1003:1003 /srv/gha-cache
   sudo chmod 755 /srv/gha-cache
   ```

3. **Workflow uses gha-opencache:**
   ```yaml
   - uses: amulya-labs/gha-opencache@v3
     with:
       path: .venv
       key: poetry-${{ hashFiles('poetry.lock') }}
   ```

See [gha-opencache](https://github.com/amulya-labs/gha-opencache) for backend configuration options.

**Debug container issues:**
```bash
# Test container manually
sudo -u ci-docker docker run --rm -it rust:latest bash

# Check container logs
sudo journalctl -u gha-{service} -n 100 | grep -i error
```

---

## GPU Support

### Prerequisites

```bash
# Install NVIDIA drivers
sudo apt-get install nvidia-driver-535

# Install NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### GPU Workflow

```yaml
jobs:
  train:
    runs-on: [self-hosted, linux, gpu, max, generic]
    container:
      image: pytorch/pytorch:2.0.1-cuda11.8-cudnn8-runtime
    steps:
      - uses: actions/checkout@v5
      - run: python train.py --gpu
```

---

## File Locations

```
/srv/gha/                                    # Runner homes
├── my-linux-cpu-small-1/
│   ├── _work/                              # Job workspaces (persists)
│   ├── .cache/                             # Runner-specific cache
│   ├── .runner                             # Runner config
│   └── run.sh                              # Runner executable
└── my-linux-cpu-medium-1/
    └── ...

/srv/gha-cache/                              # Shared cache storage (all runners)
├── poetry-Linux-abc123/                     # Poetry virtualenv cache
│   └── .venv/
├── cargo-def456/                            # Cargo cache
│   └── .cargo/
└── npm-ghi789/                              # npm cache
    └── .npm/

/etc/systemd/system/                         # Service files
├── gha-my-linux-cpu-small-1.service
└── gha-my-linux-cpu-medium-1.service
```

---

## Security Considerations

### Container Isolation

Containers provide process isolation but share the kernel:
- Use trusted images only
- Pin image versions
- Scan images for vulnerabilities

### Secrets Management

```yaml
- run: echo "${{ secrets.API_KEY }}" | docker login ...
  # Secrets are masked in logs
```

### Network Security

Containers can access:
- Host network (via `--network host`)
- Other containers (via service containers)
- External internet

Firewall rules apply at host level.

---

## Performance Tips

1. **Use slim images** when possible (`python:3.12-slim` vs `python:3.12`)
2. **Pre-build custom images** with common dependencies
3. **Cache aggressively** but invalidate when needed
4. **Use local cache** instead of cloud cache
5. **Pin dependency versions** for reproducible builds
6. **Use multi-stage Docker builds** to reduce image size
7. **Leverage Docker layer caching** in image builds

---

## Limitations

While gha-runnerd provides significant benefits, be aware of these limitations:

### Platform Support
- **Linux only** - Currently supports Ubuntu 20.04+ and Debian 11+ with systemd
- **No Windows/macOS** - Host-based approach requires Linux-specific features
- **systemd required** - Uses systemd for service management

### Runner Lifecycle
- **No auto-scaling** - Runners are static; no dynamic scaling based on queue depth
- **Manual updates** - Runner binary updates require manual intervention (use `--upgrade` command)
- **No ephemeral runners** - Runners persist across jobs (workspaces are reused)

### Resource Management
- **No automatic resource cleanup** - Workspaces (`_work`) persist and grow over time
- **Manual monitoring required** - No built-in metrics or alerting for runner health
- **Shared host resources** - Multiple runners compete for host CPU/memory/disk

### Security Considerations
- **Shared kernel** - Containers provide process isolation but share the host kernel
- **Persistent workspaces** - Job artifacts remain on disk unless manually cleaned
- **No built-in secrets rotation** - GitHub tokens and secrets management is manual

### Operational Overhead
- **Manual deployment** - No automated fleet management or orchestration
- **Limited observability** - Relies on systemd logs and manual inspection
- **No built-in backup/restore** - Configuration and state backup is manual

### When NOT to Use gha-runnerd

Consider alternatives if you need:
- **Kubernetes-native deployment** → Use [actions-runner-controller](https://github.com/actions/actions-runner-controller)
- **Ephemeral runners** → Use GitHub-hosted runners or ARC
- **Automatic scaling** → Use ARC with HPA or GitHub-hosted runners
- **Windows/macOS runners** → Use GitHub-hosted runners or other solutions
- **Zero maintenance** → Use GitHub-hosted runners

---

## Frequently Asked Questions (FAQ)

### General Questions

**Q: When should I use gha-runnerd instead of GitHub-hosted runners?**

A: Consider gha-runnerd when you:
- Run 50+ builds/day and want faster caching (sub-second vs 10-60s)
- Need specialized hardware (GPU, custom CPU architectures)
- Have compliance or data residency requirements
- Want predictable costs (pay for hardware, not per-minute)
- Need to avoid the 6-hour job timeout limit

GitHub-hosted runners are better for:
- Small projects with occasional builds
- Windows or macOS builds
- Teams wanting zero infrastructure maintenance

**Q: Can I run multiple gha-runnerd instances on the same host?**

A: Yes! Just ensure runner names are unique across your organization. You can:
- Use different prefixes per host (`dev`, `staging`, `prod`)
- Deploy different runner sizes on the same host
- Mix CPU and GPU runners on the same host (if hardware supports it)

**Q: How do I scale my runner fleet?**

A: gha-runnerd uses static runner allocation. To scale:
1. **Vertical scaling**: Increase runner sizes in `config.yml` (small → medium → large)
2. **Horizontal scaling**: Add more runner instances to `config.yml` (`cpu-small-1`, `cpu-small-2`, etc.)
3. **Multi-host scaling**: Deploy gha-runnerd on additional hosts with unique prefixes

There's no auto-scaling. If you need dynamic scaling, consider [actions-runner-controller](https://github.com/actions/actions-runner-controller).

### Runner Management

**Q: What happens when a runner goes offline?**

A:
- **Temporary offline**: GitHub queues jobs until the runner returns (up to 24 hours)
- **Long-term offline**: After 30 days, GitHub automatically removes the runner registration
- **Planned maintenance**: Stop the systemd service, perform maintenance, restart service

**Q: How do I update runner binaries?**

A: Use the `--upgrade` command:
```bash
# 1. Update version in config.yml
vim config.yml  # Change runner.version

# 2. Run upgrade
./deploy-host.py --upgrade
```

The upgrade preserves runner registration and waits for current jobs to complete.

**Q: Can I remove a runner without deleting it from GitHub?**

A: Yes, use `--remove`:
```bash
./deploy-host.py --remove cpu-small-1
```

The runner will auto-remove from GitHub after 30 days offline. To manually remove from GitHub, use the web UI or `gh api`.

**Q: How do I move a runner to a different host?**

A: Runners are tied to their registration. To move:
1. Deploy a new runner on the new host with a different name
2. Update workflows to use the new runner labels
3. Remove the old runner once workflows are migrated

### Workflow Questions

**Q: Do I need to install dependencies on the host?**

A: No! Use containers for dependencies:
```yaml
container:
  image: python:3.11  # All Python dependencies in container
```

Only install on host if:
- Using specialized runners (category: `docker`, `bazel`)
- Requiring host-level tools (unusual)

**Q: Can I use service containers (databases, Redis, etc.)?**

A: Yes! Service containers work perfectly:
```yaml
services:
  postgres:
    image: postgres:15
```

See the [Using Service Containers](#using-service-containers) section for examples.

**Q: Why is my cache always missing?**

A: Check three things:
1. **Shared cache directory/backing store exists**: Verify the directory (e.g., `ls -la /srv/gha-cache/`) or your configured backend storage is accessible
2. **gha-opencache step is configured correctly**: Ensure your workflow uses `gha-opencache@v3` with the right `path` and `key` inputs for your environment
3. **Cache key matches**: Check for typos or unexpected changes in your cache key so restore and save steps use the same value

See [Cache Not Working](#cache-not-working) in Troubleshooting.

**Q: Can I use both containerized and non-containerized jobs?**

A: Yes! Use different runner categories:
- **Containerized jobs**: `runs-on: [self-hosted, linux, cpu, medium, generic]`
- **Host jobs** (Docker builds): `runs-on: [self-hosted, linux, cpu, medium, docker]`

### Security Questions

**Q: Is it safe to run external pull requests on self-hosted runners?**

A: **Generally no.** Self-hosted runners execute arbitrary code, so external PRs are risky. Options:
1. **Require approval**: GitHub org setting "Require approval for all outside collaborators"
2. **Use GitHub-hosted for PRs**: Mix self-hosted (for main/branches) with GitHub-hosted (for external PRs)
3. **Separate runner pool**: Dedicated runners for untrusted code with strict network isolation

See [SECURITY.md](SECURITY.md) for comprehensive security guidance.

**Q: How are secrets handled?**

A:
- Secrets are passed to workflows as environment variables
- They're masked in logs but accessible to workflow code
- **Important**: Self-hosted runners don't encrypt secrets at rest
- Treat runner hosts as if they have access to all organization secrets

**Q: Can workflows access files outside their workspace?**

A: By default, no. Workflows run with limited permissions:
- Can read/write in `/srv/gha/{runner-name}/_work/`
- Can access shared cache `/srv/gha-cache/`
- Cannot access other runners' workspaces
- Cannot access root-owned files

### Performance Questions

**Q: How much faster is local cache compared to GitHub cache?**

A: Typically:
- **GitHub cloud cache**: 10-60 seconds restore time
- **Local cache** (gha-opencache): Sub-second (often <100ms)

The speed difference compounds across multiple cache operations per workflow.

**Q: How much disk space do I need?**

A: Recommended:
- **OS + tools**: 10GB
- **Runner binaries**: ~500MB per runner
- **Docker images**: 5-20GB depending on images used
- **Cache storage**: 10-50GB (monitor `/srv/gha-cache/`)
- **Workspace**: 5-10GB per active runner

Total: 50-100GB minimum, 200GB+ recommended for production.

**Q: Can I limit disk space for caches?**

A: The cache directory isn't automatically limited. Options:
1. **Manual cleanup**: Periodically delete old caches
2. **Monitoring**: Set up alerts for disk usage
3. **Separate partition**: Mount `/srv/gha-cache` on a separate partition with size limits

### Troubleshooting

**Q: How do I debug a failing runner?**

A:
```bash
# Check service status
sudo systemctl status gha-my-linux-cpu-small-1

# View recent logs
sudo journalctl -u gha-my-linux-cpu-small-1 -n 100

# Follow logs in real-time
sudo journalctl -u gha-my-linux-cpu-small-1 -f
```

See the [Troubleshooting](#troubleshooting) section for common issues.

**Q: Where can I get help?**

A:
1. Check [Troubleshooting](#troubleshooting) section
2. Review [SECURITY.md](SECURITY.md) for security issues
3. Check [existing issues](https://github.com/amulya-labs/gha-runnerd/issues)
4. Open a [new issue](https://github.com/amulya-labs/gha-runnerd/issues/new) with details

---

## Related Projects

### gha-opencache

**[gha-opencache](https://github.com/amulya-labs/gha-opencache)** is the recommended caching action for gha-runnerd. It's a drop-in replacement for `actions/cache` with:

- **Pluggable backends**: Local disk, S3-compatible storage, Google Cloud Storage
- **Sub-second restores**: No network round-trips when using local backend
- **Configurable TTL**: Automatic cache expiration and cleanup
- **Compression options**: Reduce storage usage with configurable compression

**Quick example:**
```yaml
- uses: amulya-labs/gha-opencache@v3
  with:
    path: node_modules
    key: npm-${{ hashFiles('package-lock.json') }}
```

See the [Caching Dependencies](#caching-dependencies) section for more examples.

---

## Related Documentation

- **GitHub Docs**: https://docs.github.com/en/actions/hosting-your-own-runners
- **Docker Official Images**: https://hub.docker.com/_/

---

## Migration Guide

Migrating from another runner setup? See the comprehensive [Migration Guide](docs/MIGRATION.md) for detailed instructions:

- **From Docker-Based Runners** - Step-by-step migration from docker-compose runners
- **From GitHub-Hosted Runners** - How to switch from GitHub's hosted runners
- **From actions-runner-controller** - Migrating from Kubernetes-based ARC
- **Cache Migration** - Switch from `actions/cache` to local cache
- **Rollback Procedures** - How to safely rollback if needed

### Quick Migration Example

```bash
# From docker-compose runners
docker compose down
sudo mv /srv/gha /srv/gha.backup
./deploy-host.py

# Update workflows to use containers
# See docs/MIGRATION.md for complete details
```

---

## License

MIT License - See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
