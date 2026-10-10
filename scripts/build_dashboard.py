#!/usr/bin/env python3
"""Generate the version-controlled Grafana dashboard JSON."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
database = {"type": "postgres", "uid": "incident-postgres"}
metrics = {"type": "prometheus", "uid": "monitoring-metrics"}
panels = []


def sql_panel(title, sql, panel_type, x, y, w, h, options=None, field=None):
    panels.append({"id": len(panels)+1, "title": title, "type": panel_type,
                   "datasource": database, "gridPos": {"x": x, "y": y, "w": w, "h": h},
                   "targets": [{"refId": "A", "datasource": database, "rawSql": sql, "rawQuery": True,
                                "format": "time_series" if panel_type == "timeseries" else "table"}],
                   "options": options or {}, "fieldConfig": field or {"defaults": {}, "overrides": []}})


panels.append({"id": 1, "title": "Scope and interpretation", "type": "text", "gridPos": {"x": 0, "y": 0, "w": 24, "h": 3},
               "options": {"mode": "markdown", "content": "**Advisory analysis.** `demo` means simulated observability inputs. The default model is real local Ollama inference; the optional simulator model is a deterministic fixture. Original alert severity and AI priority are separate. Pending/unknown means insufficient analysis, not healthy. Webhook deliveries are not confirmed pages. Dedicated Kubernetes/deployment collectors and rule replay are extension points."}})
for x, title, predicate in [(0, "Open incidents", "state='open'"), (6, "Recommended urgent", "priority='urgent' AND state='open'"),
                            (12, "Pending / unknown", "priority IN ('pending','unknown')"), (18, "Failed investigations", "job_state='failed'")]:
    sql_panel(title, f"SELECT COUNT(*) AS value FROM grafana_incidents WHERE {predicate}", "stat", x, 3, 6, 3)
sql_panel("Incident triage — original severity and recommended priority",
          "SELECT id, to_timestamp(first_seen) AS started, service, environment, workload, state, original_severities, priority, summary, model_name, analysis_mode, job_state, error_code FROM grafana_incidents WHERE first_seen <= $__unixEpochTo() AND (last_seen >= $__unixEpochFrom() OR state='open') ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'investigate' THEN 1 WHEN 'unknown' THEN 2 ELSE 3 END, last_seen DESC LIMIT 200",
          "table", 0, 6, 24, 9, {"showHeader": True, "cellHeight": "sm"})
sql_panel("AI explanation and missing-evidence guidance",
          "SELECT service, workload, priority, explanation, model_name, analysis_mode FROM grafana_incidents WHERE first_seen <= $__unixEpochTo() AND (last_seen >= $__unixEpochFrom() OR state='open') ORDER BY last_seen DESC LIMIT 50",
          "table", 0, 15, 24, 7)
sql_panel("Alert episodes (each row is an occurrence)",
          "SELECT to_timestamp(starts_at) AS time, to_timestamp(COALESCE(ends_at, EXTRACT(EPOCH FROM now()))) AS timeend, service || ' / ' || alertname || ' / ' || LEFT(id,8) AS entity, CASE WHEN ends_at IS NULL THEN 'firing' ELSE 'fired (resolved)' END AS state FROM grafana_episodes WHERE starts_at <= $__unixEpochTo() AND COALESCE(ends_at, EXTRACT(EPOCH FROM now())) >= $__unixEpochFrom() ORDER BY starts_at LIMIT 100",
          "state-timeline", 0, 22, 24, 9, {"mergeValues": True, "showValue": "auto", "rowHeight": 0.8})
panels[-1]["transformations"] = [{"id": "partitionByValues", "options": {"fields": ["entity"]}}]
sql_panel("Recorded alert episodes by rule",
          "SELECT $__timeGroupAlias(to_timestamp(starts_at),'5m'), COUNT(*) AS value, alertname AS metric FROM grafana_episodes WHERE $__timeFilter(to_timestamp(starts_at)) GROUP BY 1,3 ORDER BY 1",
          "timeseries", 0, 31, 12, 8)
sql_panel("Analysis-webhook deliveries (not pages)",
          "SELECT $__timeGroupAlias(to_timestamp(received_at),'5m'), COUNT(*) AS value FROM grafana_delivery_stats WHERE $__timeFilter(to_timestamp(received_at)) GROUP BY 1 ORDER BY 1",
          "timeseries", 12, 31, 12, 8)
panels.append({"id": len(panels)+1, "title": "Replica health — annotated incidents", "type": "timeseries", "datasource": metrics,
               "gridPos": {"x": 0, "y": 39, "w": 12, "h": 8},
               "targets": [{"refId": "A", "expr": "demo_workload_available_replicas", "legendFormat": "available {{service}}"},
                           {"refId": "B", "expr": "demo_workload_desired_replicas", "legendFormat": "desired {{service}}"}]})
panels.append({"id": len(panels)+1, "title": "Request errors — annotated incidents", "type": "timeseries", "datasource": metrics,
               "gridPos": {"x": 12, "y": 39, "w": 12, "h": 8},
               "targets": [{"refId": "A", "expr": "rate(demo_request_errors_total[2m])", "legendFormat": "{{service}}"}]})
sql_panel("Scheduled review candidates (no rule changes applied)",
          "SELECT to_timestamp(created_at) AS time, mode, report FROM grafana_reviews WHERE $__timeFilter(to_timestamp(created_at)) ORDER BY created_at DESC LIMIT 10",
          "table", 0, 47, 24, 7)
dashboard = {
    "uid": "signal-sift-overview", "title": "SignalSift — incidents and rule reviews", "schemaVersion": 39, "version": 1,
    "editable": False, "tags": ["signal-sift", "advisory"], "timezone": "browser", "refresh": "10s",
    "time": {"from": "now-1h", "to": "now"}, "panels": panels,
    "annotations": {"list": [{"name": "Incident evidence", "enable": True, "hide": False, "iconColor": "#ff9830",
        "datasource": database,
        "target": {"refId": "Anno", "format": "table", "rawQuery": True,
          "rawSql": "SELECT to_timestamp(first_seen) AS time, to_timestamp(CASE WHEN state='open' THEN EXTRACT(EPOCH FROM now()) ELSE last_seen END) AS timeend, service || ': ' || COALESCE(NULLIF(summary,''),state) AS text, service || ',' || environment || ',' || priority AS tags FROM grafana_incidents WHERE first_seen <= $__unixEpochTo() AND (last_seen >= $__unixEpochFrom() OR state='open')"}}]},
}
target = root / "grafana/dashboards/overview.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(dashboard, indent=2)+"\n")
print("Grafana dashboard generated")
