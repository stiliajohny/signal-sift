"""Controllable Prometheus exporter, sample log endpoint and simulated model.

This service NEVER runs an LLM. Assessments are deterministic test fixtures.
"""
import json
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse


def create_app():
    app = FastAPI(title="SignalSift demo simulator")
    state = {"scenario": "healthy", "changed": time.time(), "errors": 0, "logs": []}

    def current():
        if state["scenario"] == "transient" and time.time()-state["changed"] >= 45:
            change("healthy")
        return state["scenario"]

    def change(name):
        state.update(scenario=name, changed=time.time())
        state["logs"].append({"_time": datetime.now(timezone.utc).isoformat(),
                             "_msg": "SIMULATED scenario changed to " + name,
                             "service": "checkout", "environment": "demo", "cluster": "compose",
                             "namespace": "demo", "workload": "checkout"})
        state["logs"] = state["logs"][-50:]

    @app.get("/healthz")
    def health():
        return {"status": "ok", "simulated": True}

    @app.get("/scenario")
    def scenario():
        return {"scenario": current(), "simulated": True}

    @app.post("/scenario/{name}")
    def set_scenario(name: str):
        if name not in {"healthy", "transient", "persistent", "capacity"}:
            raise HTTPException(400, "Choose healthy, transient, persistent or capacity")
        change(name)
        return {"scenario": name, "simulated": True}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        scenario = current()
        available = {"healthy": 3, "transient": 2, "persistent": 0, "capacity": 5}[scenario]
        desired = 8 if scenario == "capacity" else 3
        limited = int(scenario == "capacity")
        state["errors"] += 5 if scenario in {"persistent", "capacity"} else 0
        labels = '{service="checkout",environment="demo",cluster="compose",namespace="demo",workload="checkout"}'
        result = "# Demo metrics: simulated, not actual Kubernetes state.\n"
        for name, value, kind in [
            ("demo_workload_available_replicas", available, "gauge"),
            ("demo_workload_desired_replicas", desired, "gauge"),
            ("demo_hpa_scaling_limited", limited, "gauge"),
            ("demo_request_errors_total", state["errors"], "counter")]:
            result += f"# TYPE {name} {kind}\n{name}{labels} {value}\n"
        return result

    @app.post("/select/logsql/query", response_class=PlainTextResponse)
    async def logs(request: Request):
        # The simulator preserves the wire format. Real LogsQL evaluation lives in VictoriaLogs.
        await request.body()
        current()
        return '\n'.join(json.dumps(line) for line in state["logs"])+"\n"

    @app.get("/loki/api/v1/query_range")
    def loki_logs():
        current()
        return {"status": "success", "data": {"resultType": "streams", "result": [{
            "stream": {"service": "checkout", "environment": "demo", "cluster": "compose",
                       "namespace": "demo", "workload": "checkout"},
            "values": [[str(int(datetime.fromisoformat(row["_time"]).timestamp()*1e9)), row["_msg"]]
                       for row in reversed(state["logs"])]}]}}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        data = json.loads(body["messages"][-1]["content"])
        if data["task"] == "review":
            report = {"summary": "SIMULATED: review recurring rules; frequency alone does not prove noise.",
                      "candidates": [{"alertname": row["alertname"], "action": "Review impact and rule duration before tuning"}
                                     for row in data["data"]["rules"][:30]],
                      "limitations": ["Deterministic demo response; no actual model inference or rule replay"]}
        else:
            items = {e["id"]: e for e in data["data"]}
            observations = items["alerts"]["data"]
            metrics = items.get("metric:available_replicas", {}).get("data", {}).get("series", [])
            desired = items.get("metric:desired_replicas", {}).get("data", {}).get("series", [])
            available_value = float(metrics[0]["values"][-1][1]) if metrics and metrics[0]["values"] else None
            desired_value = float(desired[0]["values"][-1][1]) if desired and desired[0]["values"] else None
            priority = "unknown"
            if available_value is not None:
                priority = "urgent" if available_value == 0 else "investigate"
                if observations["state"] == "resolved":
                    priority = "investigate"  # Recovery alone does not classify an episode as harmless.
            cited = ["alerts"] + (["metric:available_replicas"] if metrics else [])
            report = {"priority": priority,
                      "summary": "SIMULATED assessment: " + priority,
                      "explanation": "Deterministic fixture. Available replicas=" + str(available_value) + "; desired replicas=" + str(desired_value) + ". An engineer must validate service impact.",
                      "suspected_cause": None, "evidence_ids": cited,
                      "missing_evidence": ["Actual model inference", "Kubernetes events", "Deployment history"],
                      "next_checks": ["Check workload readiness and scaling conditions", "Check request failures and recent deployments"]}
        return {"choices": [{"message": {"role": "assistant", "content": json.dumps(report)}}]}

    return app


def main():
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=9100)


if __name__ == "__main__":
    main()
