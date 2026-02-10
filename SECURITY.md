# Security Policy

## Overview

Self-hosted GitHub Actions runners execute untrusted code from workflows. Understanding the security model and following best practices is critical to protecting your infrastructure.

## Security Model

### Runner Isolation

**Host-based runners (gha-runnerd) run directly on the host:**
- Runners execute as the `ci-docker` user (UID 1003)
- Systemd resource limits provide basic resource isolation (CPU, memory, PIDs)
- **Containers provide process isolation but share the host kernel**
- Docker socket access means workflows can execute arbitrary containers

**Key principle:** Self-hosted runners should only run workflows from trusted repositories in your organization.

### What Workflows Can Access

When a workflow runs on your self-hosted runner, it can:

1. **Execute arbitrary code** as the runner user
2. **Access the Docker socket** to run any container
3. **Access the host network** and make external connections
4. **Read/write files** in the runner's workspace
5. **Access shared cache** at `/srv/gha-cache`
6. **Persist data** across workflow runs in `_work` directory

**Workflows CANNOT (by default):**
- Access files outside the runner's home directory
- Execute as root (unless explicitly granted via sudo)
- Access other runners' workspaces

### Attack Surface

**Primary risks:**
1. **Malicious workflows** - Pull requests from external contributors can run arbitrary code
2. **Supply chain attacks** - Compromised actions or dependencies
3. **Container escapes** - Kernel vulnerabilities allowing container breakout
4. **Resource exhaustion** - Workflows consuming all CPU/memory/disk

## Token Handling

### Registration Tokens

- **Lifetime**: 1 hour from creation
- **Scope**: Organization-level runner registration
- **Usage**: Single-use (consumed during runner registration)
- **Fetching**: Automatically fetched via `gh` CLI (requires org admin permissions)

**Best practices:**
- Never commit registration tokens to version control
- Tokens are automatically managed by the deployment script
- Re-run deployment to refresh expired tokens

### GitHub Secrets

- Secrets defined in your repository/organization settings are available to workflows
- Secrets are masked in logs but accessible to workflow code
- **Self-hosted runners:** Secrets are never encrypted at rest on the runner
- Treat runner hosts as if they have access to all organization secrets

## Best Practices

### 1. Separate Runner Infrastructure

```
Recommended: Dedicated hosts for self-hosted runners
❌ BAD:  Run runners on production database servers
✅ GOOD: Isolated VMs or bare metal for runner fleet
```

**Rationale:** Compromised workflows should not have access to production systems.

### 2. Only Run Trusted Workflows

```yaml
# Restrict workflows to organization members
on:
  pull_request:
    types: [opened, synchronize]
  pull_request_target: # ⚠️ Be very careful with this

# Require manual approval for external PRs
# (GitHub organization setting: "Require approval for all outside collaborators")
```

**Critical:** External pull requests from forks run with the fork's code. For public repositories, **require manual approval** for first-time contributors.

### 3. Limit Docker Socket Exposure

The Docker socket is powerful but dangerous:

```yaml
# ❌ AVOID: Mounting Docker socket unnecessarily
- run: docker run -v /var/run/docker.sock:/var/run/docker.sock ...

# ✅ BETTER: Use specialized runners for Docker builds
runs-on: [self-hosted, linux, cpu, medium, docker]
```

**For specialized runners (docker category):**
- Use only for trusted workflows requiring Docker builds
- Consider using dedicated runner hosts
- Monitor container activity

### 4. Network Security

**Firewall Configuration:**
```bash
# Outbound: Allow HTTPS to GitHub (required)
# Inbound: No ports need to be exposed (runners poll GitHub)

# Restrict access to internal networks if possible
sudo ufw default deny incoming
sudo ufw allow out 443/tcp
sudo ufw enable
```

**Consider:**
- Network segmentation (separate VLAN for runners)
- Egress filtering to block access to internal services
- Logging network connections for audit

### 5. Secrets Management

```yaml
# ✅ GOOD: Use GitHub secrets for sensitive data
- run: echo "${{ secrets.API_KEY }}" | tool login

# ❌ BAD: Hardcoding secrets
- run: export API_KEY=sk_live_12345

# ✅ GOOD: Limit secret scope to specific environments
environment: production
secrets: inherit
```

**Best practices:**
- Use environment-specific secrets (dev, staging, prod)
- Rotate secrets regularly
- Audit secret access via GitHub audit log
- Consider external secret managers (Vault, AWS Secrets Manager)

### 6. Container Image Trust

```yaml
# ✅ GOOD: Pin exact image versions
container:
  image: node:20.11.0  # Specific SHA256 is even better

# ❌ BAD: Using :latest or unverified images
container:
  image: node:latest

# ✅ GOOD: Use official images from trusted registries
container:
  image: docker.io/library/node:20.11.0
```

**Recommendations:**
- Use official images from Docker Hub, GitHub Container Registry, or your private registry
- Scan images for vulnerabilities (Trivy, Snyk, etc.)
- Pin to specific versions or SHA256 digests
- Regularly update base images

### 7. Workspace Permissions

The cleanup hook (`cleanup-workspace.sh`) runs with sudo to fix permissions:

```bash
# Allowed in /etc/sudoers.d/gha-runner-cleanup
#1003 ALL=(root) NOPASSWD: /usr/bin/chown -R 1003:1003 /srv/gha/*/_work
```

**Security considerations:**
- Limited to workspace directory only
- No other sudo privileges granted
- Required for Docker containers that run as root

### 8. Resource Limits

Configured via systemd to prevent resource exhaustion:

```yaml
# config.yml
sizes:
  medium:
    cpus: 6.0         # CPU quota (6 cores)
    mem_limit: "16g"  # Memory limit
    pids_limit: 4096  # Max processes
```

**Recommendations:**
- Set conservative limits for untrusted workflows
- Monitor resource usage with `systemctl status gha-*`
- Use `max` size only for fully trusted workflows

### 9. Audit and Monitoring

**Enable logging:**
```bash
# View runner logs
sudo journalctl -u gha-* -f

# Export logs to centralized logging (Fluentd, Loki, etc.)
# Configure journald forwarding to your log aggregation system
```

**Monitor:**
- Failed login attempts
- Unusual network connections
- Resource usage spikes
- Container activity (`docker ps`, `docker logs`)

**GitHub audit log:**
- Track runner registration/removal
- Monitor workflow runs
- Review secret access

### 10. Regular Updates

```bash
# Update runner binaries
# 1. Update version in config.yml
# 2. Re-deploy
sudo -E ./deploy-host.py

# Update host OS
sudo apt update && sudo apt upgrade -y

# Update container images (rebuild custom images)
docker pull rust:1.75
docker pull node:20
```

**Schedule:**
- Weekly: Review security advisories
- Monthly: Update runner binaries, OS patches
- Quarterly: Audit runner configurations, review access

## Incident Response

### If you suspect a runner compromise:

1. **Immediately stop the runner:**
   ```bash
   sudo systemctl stop gha-{prefix}-linux-{runner-name}
   ```

2. **Revoke organization tokens and secrets**
3. **Review GitHub audit log** for suspicious activity
4. **Inspect runner logs:**
   ```bash
   sudo journalctl -u gha-{runner-name} --since "1 hour ago"
   ```

5. **Check for persistence mechanisms:**
   ```bash
   # Check for cron jobs, systemd timers, startup scripts
   sudo crontab -u ci-docker -l
   systemctl list-timers
   ```

6. **Investigate container activity:**
   ```bash
   docker ps -a
   docker inspect <container-id>
   ```

7. **Wipe and rebuild** the runner host if compromise is confirmed

## Reporting Security Issues

If you discover a security vulnerability in gha-runnerd itself, please report it via GitHub Security Advisories or email the maintainers directly. Do not open public issues for security vulnerabilities.

## Additional Resources

- [GitHub: Security hardening for self-hosted runners](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#hardening-for-self-hosted-runners)
- [OWASP: CI/CD Security Cheatsheet](https://cheatsheetseries.owasp.org/cheatsheets/CI_CD_Security_Cheat_Sheet.html)
- [Docker: Security best practices](https://docs.docker.com/engine/security/)
