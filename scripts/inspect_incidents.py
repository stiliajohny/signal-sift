#!/usr/bin/env python3
"""Read local incidents without putting the bearer token in shell history."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parents[1]
values = {}
if (root / ".env").exists():
    for line in (root / ".env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
values.update({k: v for k, v in os.environ.items() if k in {"API_TOKEN", "API_PORT"}})
token = values.get("API_TOKEN", "")
if not token:
    raise SystemExit("Run scripts/init_env.py first, or set API_TOKEN")
request = Request("http://127.0.0.1:" + values.get("API_PORT", "8000") + "/incidents",
                  headers={"Authorization": "Bearer " + token})
try:
    with urlopen(request, timeout=10) as response:
        print(json.dumps(json.load(response), indent=2))
except Exception as error:
    raise SystemExit("Incident request failed: " + type(error).__name__) from None
