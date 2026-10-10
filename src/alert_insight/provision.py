"""Render Prometheus/Alertmanager configuration from Compose environment."""
import os
from pathlib import Path

import yaml


def main():
    destination = Path(os.getenv("OUTPUT_DIR", "/generated"))
    destination.mkdir(parents=True, exist_ok=True)
    token = os.environ["API_TOKEN"]
    if not token:
        raise ValueError("API_TOKEN must not be empty")
    rules = {"groups": [{"name": "demo-workload", "rules": [
        {"alert": "DemoPodUnavailable", "expr": os.getenv("POD_ALERT_EXPR", "demo_workload_available_replicas < demo_workload_desired_replicas"),
         "for": os.getenv("DEMO_RULE_FOR", "15s"), "labels": {"severity": "warning"},
         "annotations": {"summary": "Demo workload has unavailable replicas", "description": "Simulated pod-health signal; evaluate workload health and impact."}},
        {"alert": "DemoHPAScalingLimited", "expr": os.getenv("HPA_ALERT_EXPR", "demo_hpa_scaling_limited == 1"),
         "for": os.getenv("DEMO_RULE_FOR", "15s"), "labels": {"severity": "warning"},
         "annotations": {"summary": "Demo HPA reached its limit", "description": "Simulated scaling signal; reaching a limit alone is not proof of an incident."}}
    ]}]}
    prometheus = {
        "global": {"scrape_interval": os.getenv("SCRAPE_INTERVAL", "5s"), "evaluation_interval": "5s"},
        "alerting": {"alertmanagers": [{"static_configs": [{"targets": [os.getenv("ALERTMANAGER_TARGET", "alertmanager:9093")]}]}]},
        "rule_files": ["/etc/prometheus/generated/demo-rules.yml"],
        "scrape_configs": [
            {"job_name": "demo-workload", "static_configs": [{"targets": [os.getenv("PROMETHEUS_SCRAPE_TARGET", "simulator:9100")]}]},
            {"job_name": "signal-sift", "static_configs": [{"targets": ["api:8000"]}]}]
    }
    alertmanager = {
        "route": {"receiver": "analysis", "group_by": ["service", "environment", "cluster", "namespace", "workload"],
                  "group_wait": "5s", "group_interval": "10s", "repeat_interval": "1h"},
        "receivers": [{"name": "analysis", "webhook_configs": [{
            "url": os.getenv("ANALYSIS_WEBHOOK_URL", "http://api:8000/webhooks/alertmanager"),
            "send_resolved": True, "http_config": {"authorization": {"type": "Bearer", "credentials_file": "/etc/alertmanager/generated/webhook-token"}}
        }]}]
    }
    for name, payload in [("prometheus.yml", prometheus), ("demo-rules.yml", rules), ("alertmanager.yml", alertmanager)]:
        (destination/name).write_text(yaml.safe_dump(payload, sort_keys=False))
    # Alertmanager's nobody group can read the mounted token; configuration runs as root.
    (destination/"webhook-token").write_text(token)
    if os.geteuid() == 0:
        os.chown(destination/"webhook-token", 0, 65534)
        (destination/"webhook-token").chmod(0o440)
    else:
        (destination/"webhook-token").chmod(0o600)
    print("Monitoring configuration generated")


if __name__ == "__main__":
    main()
