#!/usr/bin/env python3
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; left unchanged")
text = (root / ".env.example").read_text()
for name in ["POSTGRES_PASSWORD", "GRAFANA_DB_PASSWORD", "GRAFANA_ADMIN_PASSWORD", "API_TOKEN"]:
    text = text.replace(name + "=local-demo-change-me", name + "=" + secrets.token_urlsafe(32))
target.write_text(text)
target.chmod(0o600)
print("Created .env with local demo credentials. Grafana user: admin; password: GRAFANA_ADMIN_PASSWORD in .env.")
