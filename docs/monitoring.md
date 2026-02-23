# Monitoring & Observability

This guide covers monitoring gha-runnerd deployed runners using built-in CLI commands, systemd journal, and Prometheus/Grafana.

## Health Checks

### Quick status check

```bash
# Check all runners
./deploy-host.py --health

# JSON output (for scripting)
./deploy-host.py --health --json

# Check only Docker pool runners
./deploy-host.py --health --pool docker
```

Exit codes: `0` = all healthy, `1` = problems detected.

The health check reports:
- **Systemd status**: whether each runner's service is active
- **GitHub status**: whether GitHub sees the runner as online/offline/busy
- **Disk space**: free space on `runner_base` and `cache.base_dir`

### systemd status commands

```bash
# Status of all runner services
sudo systemctl status gha-*

# Check if a specific runner is active
sudo systemctl is-active gha-my-linux-cpu-small-1.service

# List all runner services
sudo systemctl list-units 'gha-*' --all
```

## Logs

### journalctl

Runner output goes to the systemd journal. Filter by unit name pattern:

```bash
# Follow all runner logs in real-time
sudo journalctl -u 'gha-*' -f

# Logs from a specific runner
sudo journalctl -u gha-my-linux-cpu-small-1.service

# Last hour of logs
sudo journalctl -u 'gha-*' --since '1 hour ago'

# Only errors/warnings
sudo journalctl -u 'gha-*' -p warning

# Logs since last boot
sudo journalctl -u 'gha-*' -b

# JSON output for processing
sudo journalctl -u 'gha-*' -o json --since today
```

### Log shipping with Promtail/Loki

Example Promtail config to ship runner logs to Loki:

```yaml
# /etc/promtail/config.yml
server:
  http_listen_port: 9080

positions:
  filename: /var/lib/promtail/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: gha-runners
    journal:
      labels:
        job: gha-runners
        host: ${HOSTNAME}
      path: /var/log/journal
    relabel_configs:
      # Only capture gha-* units
      - source_labels: ['__journal__systemd_unit']
        regex: 'gha-.*\.service'
        action: keep
      - source_labels: ['__journal__systemd_unit']
        target_label: unit
      - source_labels: ['__journal_priority_keyword']
        target_label: level
```

## Prometheus Metrics

### Setup

The `--metrics` command writes a [Prometheus textfile](https://github.com/prometheus/node_exporter#textfile-collector) that node_exporter picks up automatically.

#### 1. Configure node_exporter

Ensure node_exporter has the textfile collector enabled:

```bash
# In node_exporter's systemd unit or startup flags:
--collector.textfile.directory=/var/lib/prometheus/node-exporter
```

#### 2. Set up a cron job

```bash
# /etc/cron.d/gha-runner-metrics
* * * * * root /path/to/deploy-host.py --metrics --config /path/to/config.yml
```

Or with a custom output path:

```bash
* * * * * root /path/to/deploy-host.py --metrics --metrics-path /custom/path/gha-runners.prom
```

You can also set the path in `config.yml`:

```yaml
metrics:
  textfile_path: "/var/lib/prometheus/node-exporter/gha-runners.prom"
```

#### 3. Verify

```bash
# Generate metrics manually
./deploy-host.py --metrics

# Check the output
cat /var/lib/prometheus/node-exporter/gha-runners.prom
```

### Available metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `gha_runner_up` | gauge | name, type, size | 1 if systemd service is active |
| `gha_runner_busy` | gauge | name | 1 if runner is executing a job |
| `gha_runner_configured_total` | gauge | | Total configured runners in config.yml |
| `gha_runner_disk_bytes_free` | gauge | path | Free disk space in bytes |

### Grafana queries

```promql
# Number of active runners
sum(gha_runner_up)

# Runners that are down
gha_runner_up == 0

# Busy runners
sum(gha_runner_busy)

# Runner utilization (busy / total active)
sum(gha_runner_busy) / sum(gha_runner_up) * 100

# Disk space remaining (GB)
gha_runner_disk_bytes_free / 1024 / 1024 / 1024

# Alert: runner down for >5 minutes
gha_runner_up == 0  # use with for: 5m in alert rule
```

### Example Grafana alert rule

```yaml
groups:
  - name: gha-runners
    rules:
      - alert: GHARunnerDown
        expr: gha_runner_up == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Runner {{ $labels.name }} is down"

      - alert: GHARunnerDiskLow
        expr: gha_runner_disk_bytes_free < 10737418240  # 10GB
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Low disk space on {{ $labels.path }}"
```
