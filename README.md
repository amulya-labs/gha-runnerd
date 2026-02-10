# GitHub Actions Self-Hosted Runner Stack

Host-based runners with **container-first workflows** for maximum flexibility and performance.

## Philosophy

- **Generic or specialized runners** - `cpu`/`gpu` types with optional category
- **Dependencies in containers** - Use official images (rust:latest, node:20, etc.) when possible
- **Specialized runners** - Optional category for cases requiring host access (Docker builds, etc.)
- **Fast local caching** - `corca-ai/local-cache` for zero network overhead
- **Full `jobs.container` support** - No nested container issues

---

## Why gha-runnerd?

**Choose gha-runnerd when you need:**

- **Zero nested container issues** - Unlike docker-in-docker runners, gha-runnerd runs on the host and fully supports `jobs.container`, avoiding compatibility problems with Node-based actions and complex container setups
- **Lightning-fast caching** - Local cache with sub-second restore times vs GitHub-hosted runners (10-60s cache restore)
- **Full control over infrastructure** - Custom hardware, GPUs, specialized build tools, compliance requirements, or air-gapped environments
- **Predictable costs** - No per-minute charges; pay only for your hardware
- **Container-first workflows** - Use official images (rust:latest, node:20, python:3.11) without pre-installing dependencies on the host

**Comparison with alternatives:**

| Feature | gha-runnerd | GitHub-hosted | actions-runner-controller | docker-compose runners |
|---------|-------------|---------------|---------------------------|------------------------|
| `jobs.container` support | ✅ Full | ✅ Full | ✅ Full | ❌ Nested container issues |
| Cache performance | ⚡ Sub-second | 🐢 10-60s | ⚡ Fast (cluster-dependent) | ⚡ Fast |
| Kubernetes required | ❌ No | N/A | ✅ Yes | ❌ No |
| GPU support | ✅ Yes | ✅ Limited | ✅ Yes | ✅ Yes |
| Setup complexity | 🟢 Low (5 min) | N/A | 🟡 Medium-High | 🟢 Low |
| Cost model | Fixed (hardware) | Per-minute | Fixed (cluster) | Fixed (hardware) |

**Who is this for?**

- Teams running 50+ builds/day where cache performance and costs matter
- Organizations with compliance or data residency requirements
- Projects needing GPU, specialized hardware, or custom tooling
- Teams migrating from GitHub-hosted runners to reduce costs
- Developers wanting simple self-hosted runners without Kubernetes overhead

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

## Quick Start

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

## Setup

### Prerequisites

```bash
# Install Docker
curl -fsSL https://get.docker.com | sudo sh

# Create ci-docker user (UID 1003)
sudo useradd -m -u 1003 ci-docker
sudo usermod -aG docker ci-docker

# Setup workspace and shared cache directory
sudo mkdir -p /srv/gha /srv/gha-cache
sudo chown -R 1003:1003 /srv/gha /srv/gha-cache

# Install Python dependencies
pip install -r requirements.txt
```

> **Note:** `/srv/gha-cache` is a shared cache directory used by all runners. The deploy script will create it automatically if it doesn't exist.

### Configuration

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

**Use `corca-ai/local-cache`** for fast local caching with the shared cache directory:

```yaml
# Python (Poetry with virtualenvs-in-project: true)
- name: Cache Poetry dependencies
  id: cache-poetry
  uses: corca-ai/local-cache@v2
  with:
    path: .venv
    key: poetry-${{ runner.os }}-${{ hashFiles('**/poetry.lock') }}
    restore-keys: |
      poetry-${{ runner.os }}-
    base: /srv/gha-cache

- name: Warn on cache miss
  if: steps.cache-poetry.outputs.cache-hit != 'true'
  run: echo "::warning::Poetry cache miss. Installing from scratch."

# Node.js
- uses: corca-ai/local-cache@v2
  with:
    path: ~/.npm
    key: npm-${{ runner.os }}-${{ hashFiles('**/package-lock.json') }}
    restore-keys: |
      npm-${{ runner.os }}-
    base: /srv/gha-cache

# Rust (separate caches for cargo and build artifacts)
- uses: corca-ai/local-cache@v2
  with:
    path: ~/.cargo
    key: cargo-${{ runner.os }}-${{ hashFiles('**/Cargo.lock') }}
    restore-keys: |
      cargo-${{ runner.os }}-
    base: /srv/gha-cache
- uses: corca-ai/local-cache@v2
  with:
    path: target
    key: target-${{ runner.os }}-${{ hashFiles('**/Cargo.lock') }}
    restore-keys: |
      target-${{ runner.os }}-
    base: /srv/gha-cache
```

**Best practices:**
- Always specify `base: /srv/gha-cache` to share cache across all runners
- Use `restore-keys` for partial matching (falls back to older cache if exact match fails)
- Add `${{ runner.os }}` to cache keys to avoid cross-platform issues
- Add a "Warn on cache miss" step to make cache misses visible in logs

**Note:** `corca-ai/local-cache` uses single paths per cache. For multiple directories, use separate cache steps.

**Common cache paths:**
- Python: `.venv` (with Poetry's `virtualenvs-in-project: true`)
- Node: `~/.npm` or `node_modules`
- Rust: `~/.cargo` and `target/` (separate caches)
- Go: `~/go/pkg/mod` or `~/.cache/go-build`
- Maven: `~/.m2/repository`
- Gradle: `~/.gradle/caches`

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

# Deploy with verbose logging
./deploy-host.py --verbose
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
  uses: corca-ai/local-cache@v2
  with:
    path: ~/.cargo/registry
    key: deps-${{ runner.os }}-${{ hashFiles('Cargo.lock') }}
    restore-keys: |
      deps-${{ runner.os }}-
    base: /srv/gha-cache

- name: Cache build artifacts
  uses: corca-ai/local-cache@v2
  with:
    path: target
    key: build-${{ runner.os }}-${{ hashFiles('src/**/*.rs') }}
    restore-keys: |
      build-${{ runner.os }}-
    base: /srv/gha-cache
```

### Conditional Caching

```yaml
- uses: corca-ai/local-cache@v2
  if: ${{ !env.ACT }}  # Skip in local testing
  with:
    path: ~/.cache
    key: cache-key
    base: /srv/gha-cache
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

**Root cause:** Docker containers run as root by default, creating files the runner user can't delete. The cleanup hook fixes this before each job.

---

#### 7. Cache Not Working

**Symptom:** "Cache not found" in every workflow run despite using `corca-ai/local-cache`

**Solution:**
```bash
# 1. Verify shared cache directory exists
ls -la /srv/gha-cache/
# Should show: drwxr-xr-x 1003 1003 /srv/gha-cache

# 2. Create if missing
sudo mkdir -p /srv/gha-cache
sudo chown 1003:1003 /srv/gha-cache
sudo chmod 755 /srv/gha-cache

# 3. Verify workflow has `base: /srv/gha-cache`
```

**In your workflow:**
```yaml
- uses: corca-ai/local-cache@v2
  with:
    path: .venv
    key: poetry-${{ hashFiles('poetry.lock') }}
    base: /srv/gha-cache  # ← REQUIRED!
```

**Root cause:** Without `base` parameter, the action uses default cache location which may not be shared.

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

**Solution:** The deploy script installs a pre-job cleanup hook that automatically fixes workspace permissions before each job. If you see this error, re-deploy:

```bash
./deploy-host.py
```

This creates:
- `/srv/gha/{runner}/cleanup-workspace.sh` - runs before each job
- `/etc/sudoers.d/gha-runner-cleanup` - allows runner to fix permissions

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

3. **Workflow has `base` parameter:**
   ```yaml
   - uses: corca-ai/local-cache@v2
     with:
       path: .venv
       key: poetry-${{ hashFiles('poetry.lock') }}
       base: /srv/gha-cache  # Required!
   ```

Without `base: /srv/gha-cache`, the action falls back to the default cache directory (for example `$XDG_CACHE_HOME` or `$HOME/.cache`), which in this runner setup may not exist or may not be shared between runners.

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

## Related Documentation

- **GitHub Docs**: https://docs.github.com/en/actions/hosting-your-own-runners
- **Corca Local Cache**: https://github.com/corca-ai/local-cache
- **Docker Official Images**: https://hub.docker.com/_/

---

## Migration Guide

### From Docker-Based Runners

```bash
# 1. Stop old containers
docker compose down
docker ps -a --filter "name=gha-" --format "{{.Names}}" | xargs -r docker rm -f

# 2. Backup data (optional)
sudo mv /srv/gha /srv/gha.docker-backup

# 3. Deploy new setup
export REGISTER_GITHUB_RUNNER_TOKEN=<token>
./deploy-host.py

# 4. Update workflows to use containers
# Old:
#   runs-on: [self-hosted, linux, rust, medium]
# New:
#   runs-on: [self-hosted, linux, cpu, medium]
#   container:
#     image: rust:latest

# 5. Verify new setup works (run some workflows, check logs)
sudo journalctl -u 'gha-*' -f
# Test a few workflows to ensure everything works

# 6. Clean up after verification (optional but recommended)
# Remove backup
sudo rm -rf /srv/gha.docker-backup

# Clean up old Docker-based runner images (saves ~80GB)
# First, preview what will be removed:
docker images "*actions-runner-*"

# If the list looks correct, remove them:
docker rmi $(docker images "*actions-runner-*" -q)

# Note: If you see "image is referenced in multiple repositories" errors,
# this is normal for :latest tags. Run the command again with -f to force:
docker rmi -f $(docker images "*actions-runner-*" -q)

# Clean up unused Docker resources
docker system prune -af --volumes
```

### From `actions/cache` to Local Cache

```yaml
# Before (cloud cache)
- uses: actions/cache@v4
  with:
    path: ~/.cargo
    key: cargo-${{ hashFiles('Cargo.lock') }}

# After (local cache)
- uses: corca-ai/local-cache@v2  # ← Only change this line!
  with:
    path: ~/.cargo
    key: cargo-${{ hashFiles('Cargo.lock') }}
    base: /srv/gha-cache  # ← Add this line!
```

</details>

---

## License

MIT License - See [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
