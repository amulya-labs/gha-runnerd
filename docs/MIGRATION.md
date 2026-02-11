# Migration Guide

This guide helps you migrate to gha-runnerd from other runner setups.

## Table of Contents

- [From Docker-Based Runners](#from-docker-based-runners)
- [From GitHub-Hosted Runners](#from-github-hosted-runners)
- [From actions/cache to Local Cache](#from-actionscache-to-local-cache)
- [From actions-runner-controller (ARC)](#from-actions-runner-controller-arc)
- [Rollback Procedure](#rollback-procedure)

---

## From Docker-Based Runners

If you're migrating from a docker-compose based runner setup or similar:

### Step 1: Stop Old Containers

```bash
# Stop docker-compose runners
docker compose down

# Or manually remove all runners
docker ps -a --filter "name=gha-" --format "{{.Names}}" | xargs -r docker rm -f
```

### Step 2: Backup Data (Optional)

```bash
# Backup existing runner data
sudo mv /srv/gha /srv/gha.docker-backup

# Backup configurations if any
cp docker-compose.yml docker-compose.yml.backup
```

### Step 3: Deploy gha-runnerd

```bash
# Clone and setup
git clone https://github.com/amulya-labs/gha-runnerd.git
cd gha-runnerd
pip install -r requirements.txt

# Configure
cp config.example.yml config.yml
vim config.yml  # Edit with your settings

# Authenticate with GitHub
gh auth login

# Deploy
./deploy-host.py --validate  # Validate first
./deploy-host.py             # Deploy
```

### Step 4: Update Workflows

Update your workflows to use containers:

```yaml
# Before (Docker-based runners)
jobs:
  build:
    runs-on: [self-hosted, linux, rust, medium]
    steps:
      - uses: actions/checkout@v5
      - run: cargo build

# After (gha-runnerd with containers)
jobs:
  build:
    runs-on: [self-hosted, linux, cpu, medium, generic]
    container:
      image: rust:latest
    steps:
      - uses: actions/checkout@v5
      - run: cargo build
```

**Key Changes:**
- Replace language-specific labels (`rust`, `python`, `node`) with `cpu`
- Add `generic` label for containerized jobs
- Add `container:` block with appropriate image
- Use official Docker images when possible

### Step 5: Verify New Setup

```bash
# Watch logs in real-time
sudo journalctl -u 'gha-*' -f

# Check runner status
sudo systemctl status 'gha-*'

# Test with a simple workflow
# Trigger one of your workflows and verify it runs successfully
```

### Step 6: Clean Up (After Verification)

```bash
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

---

## From GitHub-Hosted Runners

Migrating from GitHub-hosted runners is straightforward but requires workflow changes:

### Step 1: Deploy gha-runnerd

Follow the [Quick Start](../README.md#quick-start) guide to deploy runners.

### Step 2: Update Workflow Labels

```yaml
# Before (GitHub-hosted)
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: pytest

# After (gha-runnerd)
jobs:
  build:
    runs-on: [self-hosted, linux, cpu, small, generic]
    container:
      image: python:3.11
    steps:
      - uses: actions/checkout@v5
      - run: pip install -r requirements.txt
      - run: pytest
```

**Key Changes:**
- Replace `ubuntu-latest` with self-hosted labels
- Remove `actions/setup-*` steps (use container images instead)
- Choose appropriate runner size (`xs`, `small`, `medium`, `large`)
- Add container image matching your language/tools

### Step 3: Update Caching

Replace GitHub's cloud cache with local cache for better performance:

```yaml
# Before (GitHub cloud cache)
- uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: pip-${{ hashFiles('requirements.txt') }}

# After (local cache)
- uses: corca-ai/local-cache@v2
  with:
    path: ~/.cache/pip
    key: pip-${{ hashFiles('requirements.txt') }}
    base: /srv/gha-cache
```

### Step 4: Gradual Migration

Migrate workflows incrementally:

1. **Start with development/test workflows** - Lower risk
2. **Monitor performance and costs** - Verify improvements
3. **Migrate production workflows** - After validation
4. **Keep some GitHub-hosted runners** - For Windows/macOS or as backup

---

## From actions/cache to Local Cache

Switch from GitHub's cloud cache to local cache for faster restores:

### Simple Conversion

```yaml
# Before (cloud cache - 10-60s restore time)
- uses: actions/cache@v4
  with:
    path: ~/.cargo
    key: cargo-${{ hashFiles('Cargo.lock') }}

# After (local cache - sub-second restore time)
- uses: corca-ai/local-cache@v2
  with:
    path: ~/.cargo
    key: cargo-${{ hashFiles('Cargo.lock') }}
    base: /srv/gha-cache  # Shared cache directory
```

### Multiple Cache Paths

```yaml
# Before
- uses: actions/cache@v4
  with:
    path: |
      ~/.cargo/bin/
      ~/.cargo/registry/index/
      ~/.cargo/registry/cache/
      ~/.cargo/git/db/
      target/
    key: cargo-${{ runner.os }}-${{ hashFiles('Cargo.lock') }}

# After (same structure)
- uses: corca-ai/local-cache@v2
  with:
    path: |
      ~/.cargo/bin/
      ~/.cargo/registry/index/
      ~/.cargo/registry/cache/
      ~/.cargo/git/db/
      target/
    key: cargo-${{ runner.os }}-${{ hashFiles('Cargo.lock') }}
    base: /srv/gha-cache
```

### Benefits

- **Performance**: Sub-second cache restore vs 10-60s for GitHub cache
- **Reliability**: No network dependency for cache operations
- **Cost**: No data transfer costs
- **API compatible**: Drop-in replacement for `actions/cache`

---

## From actions-runner-controller (ARC)

Migrating from Kubernetes-based ARC to gha-runnerd:

### When to Migrate

Consider migrating if:
- You find ARC too complex for your needs
- You don't need auto-scaling
- You want simpler operations without Kubernetes
- You have static workload patterns

### Migration Steps

#### 1. Deploy gha-runnerd on New Hosts

```bash
# On each host machine
git clone https://github.com/amulya-labs/gha-runnerd.git
cd gha-runnerd
pip install -r requirements.txt

# Configure
cp config.example.yml config.yml
vim config.yml

# Deploy
./deploy-host.py
```

#### 2. Update Runner Labels

```yaml
# Before (ARC)
jobs:
  build:
    runs-on: [self-hosted, linux, x64]
    steps:
      - uses: actions/checkout@v5
      - run: make build

# After (gha-runnerd with containers)
jobs:
  build:
    runs-on: [self-hosted, linux, cpu, medium, generic]
    container:
      image: ubuntu:22.04
    steps:
      - uses: actions/checkout@v5
      - run: make build
```

#### 3. Gradual Cutover

1. Deploy gha-runnerd with different label prefix
2. Update workflows to use new labels gradually
3. Monitor both systems during transition
4. Scale down ARC after migration complete

#### 4. Remove ARC (After Verification)

```bash
# Scale down ARC runners
kubectl delete runnerdeployment <name>

# Remove ARC if no longer needed
helm uninstall actions-runner-controller
```

### Key Differences

| Feature | ARC | gha-runnerd |
|---------|-----|-------------|
| Platform | Kubernetes | Linux host |
| Scaling | Automatic (HPA) | Manual/static |
| Complexity | High | Low |
| Ephemeral runners | Yes | No |
| Resource isolation | Pod-level | Container-level |
| Setup time | Hours | Minutes |

---

## Rollback Procedure

If you need to rollback to your previous setup:

### Rollback from Docker-Based Migration

```bash
# 1. Stop gha-runnerd runners
sudo systemctl stop 'gha-*'
sudo systemctl disable 'gha-*'

# 2. Restore backup
sudo rm -rf /srv/gha
sudo mv /srv/gha.docker-backup /srv/gha

# 3. Restart old containers
docker compose up -d

# 4. Verify runners reconnected
docker ps | grep gha-
```

### Rollback to GitHub-Hosted Runners

```yaml
# Simply revert workflow changes
jobs:
  build:
    runs-on: ubuntu-latest  # Back to GitHub-hosted
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pytest
```

### Rollback from ARC Migration

```bash
# 1. Scale up ARC runners
kubectl scale runnerdeployment <name> --replicas=5

# 2. Stop gha-runnerd
sudo systemctl stop 'gha-*'

# 3. Update workflows to use ARC labels
# (Revert label changes in workflows)
```

---

## Getting Help

If you encounter issues during migration:

1. **Check logs**: `sudo journalctl -u 'gha-*' -f`
2. **Validate config**: `./deploy-host.py --validate`
3. **Dry-run first**: `./deploy-host.py --dry-run`
4. **Open an issue**: [GitHub Issues](https://github.com/amulya-labs/gha-runnerd/issues)
5. **Review documentation**: [README](../README.md)

## Post-Migration Checklist

- [ ] All workflows running successfully on new runners
- [ ] Cache performance improved (verify with timing logs)
- [ ] No build failures due to missing dependencies
- [ ] Old runner backups can be safely removed
- [ ] Monitoring and alerting updated for new runners
- [ ] Team documentation updated with new labels/patterns
- [ ] Old runner infrastructure decommissioned
