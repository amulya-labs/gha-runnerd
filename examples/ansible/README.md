# Ansible Deployment

Deploy gha-runnerd across multiple hosts using Ansible.

## Prerequisites

- Ansible >= 2.12 on your control node
- SSH access to target hosts
- A GitHub registration token (`REGISTER_GITHUB_RUNNER_TOKEN`)

## Quick Start

1. Copy the example inventory and customize it:

```bash
cp inventory.example.ini inventory.ini
# Edit inventory.ini with your hosts, org, and runner lists
```

2. Run the playbook:

```bash
ansible-playbook -i inventory.ini playbook.yml \
  -e "github_token=$REGISTER_GITHUB_RUNNER_TOKEN"
```

## Customization

### Per-host runner lists

Override `gha_runners` per host in the inventory:

```ini
[runners]
build-1  gha_runners='["cpu-small-1", "cpu-medium-1"]'
build-2  gha_runners='["cpu-large-1", "cpu-large-docker-1"]'
gpu-1    gha_runners='["gpu-max-1"]'
```

### Enterprise scope

```ini
[runners:vars]
gha_github_scope=enterprise
gha_github_enterprise=your-enterprise
```

### Enable Prometheus metrics

```ini
[runners:vars]
gha_metrics_enabled=true
```

This creates a cron job that writes metrics every minute for node_exporter's textfile collector.

## Files

| File | Description |
|------|-------------|
| `playbook.yml` | Main playbook: installs prereqs, creates user, deploys runners |
| `inventory.example.ini` | Example inventory with host groups |
| `templates/config.yml.j2` | Jinja2 template for runner config |
