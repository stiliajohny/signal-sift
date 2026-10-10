"""Transactional alert episodes and a leased queue; PostgreSQL in deployments."""
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import Settings
from .models import Notification, digest, redact

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS incidents (
      id TEXT PRIMARY KEY, scope_key TEXT NOT NULL, scope_json TEXT NOT NULL,
      service TEXT NOT NULL, environment TEXT NOT NULL, cluster TEXT NOT NULL,
      namespace TEXT NOT NULL, workload TEXT NOT NULL, state TEXT NOT NULL,
      first_seen DOUBLE PRECISION NOT NULL, last_seen DOUBLE PRECISION NOT NULL,
      revision INTEGER NOT NULL, latest_assessment TEXT)""",
    """CREATE TABLE IF NOT EXISTS alert_episodes (
      id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
      alertname TEXT NOT NULL, original_severity TEXT NOT NULL, status TEXT NOT NULL, starts_at DOUBLE PRECISION NOT NULL,
      ends_at DOUBLE PRECISION, last_seen DOUBLE PRECISION NOT NULL, payload TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS alert_events (
      id TEXT PRIMARY KEY, episode_id TEXT NOT NULL REFERENCES alert_episodes(id),
      incident_id TEXT NOT NULL REFERENCES incidents(id), received_at DOUBLE PRECISION NOT NULL,
      status TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS webhook_deliveries (
      id TEXT PRIMARY KEY, received_at DOUBLE PRECISION NOT NULL, alert_count INTEGER NOT NULL,
      truncated_alerts INTEGER NOT NULL, receiver TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS jobs (
      incident_id TEXT PRIMARY KEY REFERENCES incidents(id), state TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0, available_at DOUBLE PRECISION NOT NULL,
      lease_until DOUBLE PRECISION, claim_token TEXT, error_code TEXT)""",
    """CREATE TABLE IF NOT EXISTS assessments (
      id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
      revision INTEGER NOT NULL, created_at DOUBLE PRECISION NOT NULL, priority TEXT NOT NULL,
      summary TEXT NOT NULL, explanation TEXT NOT NULL, payload TEXT NOT NULL,
      evidence TEXT NOT NULL, model_name TEXT NOT NULL, prompt_version TEXT NOT NULL,
      mode TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS feedback (
      id TEXT PRIMARY KEY, incident_id TEXT NOT NULL REFERENCES incidents(id),
      created_at DOUBLE PRECISION NOT NULL, verdict TEXT NOT NULL, note TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS rule_reviews (
      id TEXT PRIMARY KEY, created_at DOUBLE PRECISION NOT NULL, window_start DOUBLE PRECISION NOT NULL,
      report TEXT NOT NULL, model_name TEXT NOT NULL, mode TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS incidents_scope ON incidents(scope_key, state, last_seen)",
    "CREATE INDEX IF NOT EXISTS episodes_time ON alert_episodes(starts_at)",
    "CREATE INDEX IF NOT EXISTS queue_available ON jobs(state, available_at)",
    """CREATE VIEW IF NOT EXISTS grafana_incidents AS
      SELECT i.id, i.service, i.environment, i.cluster, i.namespace, i.workload,
        i.state, i.first_seen, i.last_seen, i.revision,
        COALESCE(a.priority, 'pending') AS priority, COALESCE(a.summary, '') AS summary,
        COALESCE(a.explanation, '') AS explanation, COALESCE(a.mode, '') AS analysis_mode,
        COALESCE(a.model_name, '') AS model_name,
        j.state AS job_state, j.error_code,
        (SELECT COUNT(*) FROM alert_episodes e WHERE e.incident_id=i.id) AS episode_count,
        (SELECT GROUP_CONCAT(DISTINCT e.original_severity) FROM alert_episodes e WHERE e.incident_id=i.id) AS original_severities
      FROM incidents i LEFT JOIN assessments a ON a.id=i.latest_assessment AND a.revision=i.revision
      LEFT JOIN jobs j ON j.incident_id=i.id""",
    """CREATE VIEW IF NOT EXISTS grafana_episodes AS
      SELECT e.id, e.incident_id, e.alertname, e.original_severity, e.status, e.starts_at, e.ends_at,
        i.service, i.environment, i.cluster, i.namespace, i.workload
      FROM alert_episodes e JOIN incidents i ON i.id=e.incident_id""",
    """CREATE VIEW IF NOT EXISTS grafana_reviews AS
      SELECT id, created_at, report, mode FROM rule_reviews""",
    """CREATE VIEW IF NOT EXISTS grafana_delivery_stats AS
      SELECT received_at, alert_count, truncated_alerts FROM webhook_deliveries""",
]


class Connection:
    def __init__(self, conn, postgres: bool):
        self.conn, self.postgres = conn, postgres

    def execute(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql.replace("?", "%s") if self.postgres else sql, params)


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.postgres = settings.database_url.startswith("postgresql://")

    @contextmanager
    def transaction(self, *, snapshot=False):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            conn = psycopg.connect(self.settings.database_url, row_factory=dict_row, connect_timeout=10)
            conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ" if snapshot else "BEGIN")
        else:
            file = self.settings.database_url.removeprefix("sqlite:///")
            Path(file).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(file, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield Connection(conn, self.postgres)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        with self.transaction() as c:
            if self.postgres:
                c.execute("SELECT pg_advisory_xact_lock(738913201)")
            for statement in SCHEMA:
                if self.postgres:
                    statement = statement.replace("CREATE VIEW IF NOT EXISTS", "CREATE OR REPLACE VIEW")
                    statement = statement.replace("GROUP_CONCAT(DISTINCT e.original_severity)", "STRING_AGG(DISTINCT e.original_severity, ',')")
                c.execute(statement)
            role = self.settings.grafana_role
            if self.postgres and role:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
                    raise ValueError("Invalid Grafana read role")
                c.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
                c.execute(f'GRANT SELECT ON grafana_incidents, grafana_episodes, grafana_reviews, grafana_delivery_stats TO "{role}"')

    def ingest(self, notification: Notification, now: float | None = None):
        now = time.time() if now is None else now
        touched, accepted = set(), 0
        with self.transaction() as c:
            if self.postgres:
                # Serialize scope creation across API replicas; workers remain independent.
                c.execute("SELECT pg_advisory_xact_lock(738913202)")
            c.execute("INSERT INTO webhook_deliveries VALUES (?, ?, ?, ?, ?)",
                      (str(uuid.uuid4()), now, len(notification.alerts), notification.truncatedAlerts, notification.receiver))
            for alert in notification.alerts:
                event_id, episode_id = alert.event_key(), alert.episode_key()
                if c.execute("SELECT id FROM alert_events WHERE id=?", (event_id,)).fetchone():
                    continue
                existing = c.execute("SELECT * FROM alert_episodes WHERE id=?", (episode_id,)).fetchone()
                if existing and existing["status"] == "resolved" and alert.status == "firing":
                    # A delayed firing refresh must not reopen a resolved episode.
                    continue
                scope = {key: alert.labels.get(self.settings.label_map.get(key, key), "")
                         for key in self.settings.scope_fields}
                # Missing service identity isolates the episode instead of a global query/group.
                scope_key = digest(scope if scope["service"] else [scope, episode_id])
                incident = existing["incident_id"] if existing else None
                if not incident:
                    row = c.execute("SELECT id FROM incidents WHERE scope_key=? AND state='open' AND last_seen>=? ORDER BY last_seen DESC LIMIT 1",
                                    (scope_key, now-self.settings.correlation_seconds)).fetchone()
                    incident = row["id"] if row else str(uuid.uuid4())
                    if not row:
                        c.execute("INSERT INTO incidents VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, 0, NULL)",
                                  (incident, scope_key, json.dumps(scope), *scope.values(), now, now))
                alert_data = alert.model_dump(mode="json")
                if notification.truncatedAlerts:
                    alert_data["annotations"]["input_warning"] = f"Webhook omitted {notification.truncatedAlerts} alerts"
                payload = json.dumps(redact(alert_data))
                end = alert.endsAt.timestamp() if alert.status == "resolved" and alert.endsAt and alert.endsAt.year > 1 else None
                c.execute("""INSERT INTO alert_episodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                  ON CONFLICT(id) DO UPDATE SET status=excluded.status, ends_at=excluded.ends_at,
                    last_seen=excluded.last_seen, payload=excluded.payload""",
                          (episode_id, incident, alert.labels.get("alertname", "unknown"), alert.labels.get("severity", "unknown"), alert.status,
                           alert.startsAt.timestamp(), end, now, payload))
                c.execute("INSERT INTO alert_events VALUES (?, ?, ?, ?, ?)",
                          (event_id, episode_id, incident, now, alert.status))
                touched.add(incident)
                accepted += 1
            for incident in touched:
                active = c.execute("SELECT COUNT(*) AS n FROM alert_episodes WHERE incident_id=? AND status='firing'", (incident,)).fetchone()["n"]
                c.execute("UPDATE incidents SET revision=revision+1, last_seen=?, state=? WHERE id=?",
                          (now, "open" if active else "resolved", incident))
                c.execute("""INSERT INTO jobs(incident_id,state,attempts,available_at) VALUES (?, 'queued', 0, ?)
                  ON CONFLICT(incident_id) DO UPDATE SET
                  state=CASE WHEN jobs.state='running' THEN 'running' ELSE 'queued' END,
                  attempts=CASE WHEN jobs.state='running' THEN jobs.attempts ELSE 0 END,
                  available_at=excluded.available_at, error_code=NULL""", (incident, now))
        return {"accepted_events": accepted, "incident_ids": sorted(touched),
                "truncated_alerts": notification.truncatedAlerts}

    def claim(self, now: float | None = None):
        now = time.time() if now is None else now
        with self.transaction() as c:
            c.execute("UPDATE jobs SET state='failed', error_code='lease_exhausted' WHERE state='running' AND lease_until<? AND attempts>=?",
                      (now, self.settings.max_attempts))
            sql = """SELECT j.incident_id, j.attempts, i.revision FROM jobs j JOIN incidents i ON i.id=j.incident_id
              WHERE ((j.state='queued' AND j.available_at<=?) OR (j.state='running' AND j.lease_until<?))
              AND j.attempts<? ORDER BY j.available_at LIMIT 1"""
            if self.postgres:
                sql += " FOR UPDATE OF j SKIP LOCKED"
            row = c.execute(sql, (now, now, self.settings.max_attempts)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["claim_token"] = str(uuid.uuid4())
            c.execute("UPDATE jobs SET state='running', attempts=attempts+1, lease_until=?, claim_token=? WHERE incident_id=?",
                      (now+self.settings.lease_seconds, result["claim_token"], result["incident_id"]))
            return result

    def snapshot(self, incident_id: str):
        with self.transaction(snapshot=True) as c:
            row = c.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
            if not row:
                return None
            incident = dict(row)
            incident["scope"] = json.loads(incident.pop("scope_json"))
            episodes = [dict(r) for r in c.execute("SELECT * FROM alert_episodes WHERE incident_id=? ORDER BY starts_at", (incident_id,)).fetchall()]
            for episode in episodes:
                episode["alert"] = json.loads(episode.pop("payload"))
            incident["episodes"] = episodes
            incident["history"] = [dict(r) for r in c.execute("""SELECT e.alertname, COUNT(*) AS episodes,
              SUM(CASE WHEN e.status='resolved' THEN 1 ELSE 0 END) AS resolved_episodes
              FROM alert_episodes e JOIN incidents i ON i.id=e.incident_id
              WHERE i.scope_key=? AND e.starts_at>=? GROUP BY e.alertname""",
              (incident["scope_key"], time.time()-self.settings.history_hours*3600)).fetchall()]
            return incident

    def complete(self, claim, snapshot, assessment, evidence, now=None):
        now = time.time() if now is None else now
        with self.transaction() as c:
            lock = " FOR UPDATE" if self.postgres else ""
            current = c.execute("SELECT revision FROM incidents WHERE id=?" + lock, (claim["incident_id"],)).fetchone()["revision"]
            job = c.execute("SELECT * FROM jobs WHERE incident_id=?" + lock, (claim["incident_id"],)).fetchone()
            if not job or job["claim_token"] != claim["claim_token"] or job["lease_until"] < now:
                return False
            assessment_id = str(uuid.uuid4())
            c.execute("INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (assessment_id, claim["incident_id"], snapshot["revision"], now, assessment.priority,
                       assessment.summary, assessment.explanation, assessment.model_dump_json(), json.dumps(evidence),
                       self.settings.model_name, "incident-v1", self.settings.mode))
            if current == snapshot["revision"]:
                c.execute("UPDATE incidents SET latest_assessment=? WHERE id=?", (assessment_id, claim["incident_id"]))
            c.execute("UPDATE jobs SET state=?, attempts=0, available_at=?, lease_until=NULL, claim_token=NULL, error_code=NULL WHERE incident_id=?",
                      ("done" if current == snapshot["revision"] else "queued", now, claim["incident_id"]))
            return True

    def fail(self, claim, error_code: str, now=None):
        now = time.time() if now is None else now
        with self.transaction() as c:
            lock = " FOR UPDATE" if self.postgres else ""
            current = c.execute("SELECT revision FROM incidents WHERE id=?"+lock, (claim["incident_id"],)).fetchone()["revision"]
            row = c.execute("SELECT attempts FROM jobs WHERE incident_id=? AND claim_token=? AND state='running'"+lock,
                            (claim["incident_id"], claim["claim_token"])).fetchone()
            if row:
                attempts = 0 if current > claim["revision"] else row["attempts"]
                c.execute("UPDATE jobs SET state=?, attempts=?, available_at=?, error_code=?, lease_until=NULL, claim_token=NULL WHERE incident_id=? AND claim_token=?",
                          ("failed" if attempts >= self.settings.max_attempts else "queued", attempts,
                           now+min(60, 2**attempts), error_code[:80], claim["incident_id"], claim["claim_token"]))

    def incidents(self, limit=100):
        with self.transaction() as c:
            return [dict(r) for r in c.execute("SELECT * FROM grafana_incidents ORDER BY last_seen DESC LIMIT ?", (limit,)).fetchall()]

    def detail(self, incident_id):
        snapshot = self.snapshot(incident_id)
        if not snapshot:
            return None
        with self.transaction() as c:
            row = c.execute("SELECT * FROM assessments WHERE id=?", (snapshot["latest_assessment"],)).fetchone()
        snapshot["assessment"] = json.loads(row["payload"]) if row and row["revision"] == snapshot["revision"] else None
        snapshot["evidence"] = json.loads(row["evidence"]) if snapshot["assessment"] else None
        return snapshot

    def feedback(self, incident_id, verdict, note):
        with self.transaction() as c:
            if not c.execute("SELECT id FROM incidents WHERE id=?", (incident_id,)).fetchone():
                return False
            c.execute("INSERT INTO feedback VALUES (?, ?, ?, ?, ?)",
                      (str(uuid.uuid4()), incident_id, time.time(), verdict, str(redact(note))))
            return True

    def review_data(self):
        start = time.time()-self.settings.history_hours*3600
        with self.transaction() as c:
            rows = c.execute("""SELECT i.service, i.environment, e.alertname, COUNT(*) AS episode_count,
              SUM(CASE WHEN e.status='resolved' THEN 1 ELSE 0 END) AS resolved_count
              FROM alert_episodes e JOIN incidents i ON i.id=e.incident_id WHERE e.starts_at>=?
              GROUP BY i.service, i.environment, e.alertname ORDER BY COUNT(*) DESC LIMIT 100""", (start,)).fetchall()
            feedback = c.execute("SELECT verdict, COUNT(*) AS count FROM feedback WHERE created_at>=? GROUP BY verdict", (start,)).fetchall()
        return {"window_start": start, "rules": [dict(r) for r in rows], "feedback": [dict(r) for r in feedback]}

    def save_review(self, data, report):
        with self.transaction() as c:
            c.execute("INSERT INTO rule_reviews VALUES (?, ?, ?, ?, ?, ?)",
                      (str(uuid.uuid4()), time.time(), data["window_start"], json.dumps(report), self.settings.model_name, self.settings.mode))


def main():
    settings = Settings()
    settings.validate()
    Store(settings).initialize()
    print("Schema initialized")


if __name__ == "__main__":
    main()
