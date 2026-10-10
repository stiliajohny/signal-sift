import hmac
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, ValidationError

from .config import Settings
from .models import Notification
from .storage import Store


def create_app(settings: Settings | None = None, store: Store | None = None):
    settings = settings or Settings()
    settings.validate()
    store = store or Store(settings)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title="SignalSift", version="0.1.0", lifespan=lifespan,
                  docs_url="/docs" if settings.mode == "demo" else None,
                  redoc_url=None, openapi_url="/openapi.json" if settings.mode == "demo" else None)
    app.state.store = store

    bearer = HTTPBearer(auto_error=False)

    def authorized(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or credentials.scheme.lower() != "bearer" or not hmac.compare_digest(credentials.credentials.encode(), settings.api_token.encode()):
            raise HTTPException(401, "Authentication required")

    @app.get("/healthz")
    def health():
        return {"status": "ok", "mode": settings.mode}

    @app.get("/readyz")
    def ready():
        with store.transaction() as c:
            c.execute("SELECT 1")
        return {"status": "ready"}

    @app.get("/metrics")
    def metrics():
        from fastapi.responses import PlainTextResponse
        with store.transaction() as c:
            rows = c.execute("SELECT state, COUNT(*) AS count FROM jobs GROUP BY state").fetchall()
        text = '# HELP alert_insight_jobs Number of investigation jobs by state.\n# TYPE alert_insight_jobs gauge\n'
        text += ''.join(f'alert_insight_jobs{{state="{r["state"]}"}} {r["count"]}\n' for r in rows)
        return PlainTextResponse(text, media_type="text/plain; version=0.0.4")

    @app.post("/webhooks/alertmanager", dependencies=[Depends(authorized)], status_code=202)
    async def webhook(request: Request):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 1_000_000:
                raise HTTPException(413, "Webhook exceeds byte budget")
        try:
            notification = Notification.model_validate_json(bytes(data))
        except ValidationError:
            raise HTTPException(422, "Invalid Alertmanager webhook") from None
        # Acknowledge only after the event and job transaction commits.
        # Run sync I/O outside the event loop.
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(store.ingest, notification)

    @app.get("/incidents", dependencies=[Depends(authorized)])
    def incidents(limit: int = 100):
        return store.incidents(max(1, min(limit, 500)))

    @app.get("/incidents/{incident_id}", dependencies=[Depends(authorized)])
    def detail(incident_id: str):
        result = store.detail(incident_id)
        if not result:
            raise HTTPException(404, "Incident not found")
        return result

    class Feedback(BaseModel):
        verdict: Literal["correct", "incorrect", "missed_urgency", "needs_more_evidence"]
        note: str = Field(default="", max_length=2000)

    @app.post("/incidents/{incident_id}/feedback", dependencies=[Depends(authorized)])
    def feedback(incident_id: str, body: Feedback):
        if not store.feedback(incident_id, body.verdict, body.note):
            raise HTTPException(404, "Incident not found")
        return {"stored": True}

    @app.get("/reviews", dependencies=[Depends(authorized)])
    def reviews():
        import json
        with store.transaction() as c:
            rows = c.execute("SELECT * FROM grafana_reviews ORDER BY created_at DESC LIMIT 20").fetchall()
        return [{**dict(row), "report": json.loads(row["report"])} for row in rows]

    return app
