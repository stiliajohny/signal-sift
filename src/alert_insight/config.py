import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


def secret(name: str) -> str:
    """Support mounted secrets without logging their values."""
    file_name = os.getenv(name + "_FILE")
    return Path(file_name).read_text().strip() if file_name else os.getenv(name, "")


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: secret("DATABASE_URL"))
    api_token: str = field(default_factory=lambda: secret("API_TOKEN"))
    mode: str = field(default_factory=lambda: os.getenv("RUN_MODE", "live"))
    metrics_url: str = field(default_factory=lambda: os.getenv("METRICS_BASE_URL", ""))
    logs_url: str = field(default_factory=lambda: os.getenv("LOGS_QUERY_URL", ""))
    logs_backend: str = field(default_factory=lambda: os.getenv("LOGS_BACKEND", "victorialogs"))
    logs_tenant: str = field(default_factory=lambda: os.getenv("LOGS_TENANT_ID", ""))
    log_scope_fields: tuple[str, ...] = field(default_factory=lambda: tuple(os.getenv("LOG_SCOPE_FIELDS", "service,environment,cluster,namespace,workload").split(",")))
    model_url: str = field(default_factory=lambda: os.getenv("MODEL_CHAT_URL", ""))
    model_api: str = field(default_factory=lambda: os.getenv("MODEL_API", "openai"))
    model_name: str = field(default_factory=lambda: os.getenv("MODEL_NAME", "gpt-oss-120b"))
    model_context: int = field(default_factory=lambda: int(os.getenv("MODEL_CONTEXT_TOKENS", "16384")))
    model_output_tokens: int = field(default_factory=lambda: int(os.getenv("MODEL_OUTPUT_TOKENS", "2048")))
    metrics_token: str = field(default_factory=lambda: secret("METRICS_TOKEN"))
    logs_token: str = field(default_factory=lambda: secret("LOGS_TOKEN"))
    model_token: str = field(default_factory=lambda: secret("MODEL_TOKEN"))
    logs_account: str = field(default_factory=lambda: os.getenv("LOGS_ACCOUNT_ID", "0"))
    logs_project: str = field(default_factory=lambda: os.getenv("LOGS_PROJECT_ID", "0"))
    queries_file: str = field(default_factory=lambda: os.getenv("QUERIES_FILE", "config/queries.json"))
    rules_url: str = field(default_factory=lambda: os.getenv("RULES_QUERY_URL", ""))
    scope_fields: tuple[str, ...] = ("service", "environment", "cluster", "namespace", "workload")
    label_map: dict[str, str] = field(default_factory=lambda: json.loads(os.getenv("LABEL_MAP", "{}")))
    log_field_map: dict[str, str] = field(default_factory=lambda: json.loads(os.getenv("LOG_FIELD_MAP", "{}")))
    correlation_seconds: int = field(default_factory=lambda: int(os.getenv("CORRELATION_SECONDS", "300")))
    history_hours: int = field(default_factory=lambda: int(os.getenv("HISTORY_HOURS", "24")))
    query_timeout: int = field(default_factory=lambda: int(os.getenv("QUERY_TIMEOUT_SECONDS", "10")))
    model_timeout: int = field(default_factory=lambda: int(os.getenv("MODEL_TIMEOUT_SECONDS", "90")))
    max_response_bytes: int = 1_000_000
    max_model_chars: int = field(default_factory=lambda: int(os.getenv("MODEL_INPUT_CHARS", "32000")))
    max_attempts: int = 3
    lease_seconds: int = field(default_factory=lambda: int(os.getenv("JOB_LEASE_SECONDS", "300")))
    review_seconds: int = field(default_factory=lambda: int(os.getenv("REVIEW_INTERVAL_SECONDS", "3600")))
    grafana_role: str = field(default_factory=lambda: os.getenv("GRAFANA_READ_ROLE", "grafana_reader"))

    def validate(self) -> None:
        if self.mode not in {"demo", "live"}:
            raise ValueError("RUN_MODE must be demo or live")
        if self.logs_backend not in {"victorialogs", "loki"}:
            raise ValueError("LOGS_BACKEND must be victorialogs or loki")
        if self.model_api not in {"openai", "ollama"}:
            raise ValueError("MODEL_API must be openai or ollama")
        if self.model_api == "ollama":
            if not self.model_url.endswith("/api/chat") or "cloud" in self.model_name.lower():
                raise ValueError("Use the local Ollama /api/chat endpoint and a local model tag")
        if self.model_context <= self.model_output_tokens or self.model_output_tokens < 256:
            raise ValueError("Invalid model context/output budget")
        if not self.log_scope_fields or any(k not in self.scope_fields for k in self.log_scope_fields):
            raise ValueError("Invalid LOG_SCOPE_FIELDS")
        if not self.database_url or not self.api_token:
            raise ValueError("DATABASE_URL and API_TOKEN are required")
        if not (self.database_url.startswith("postgresql://") or self.database_url.startswith("sqlite:///")):
            raise ValueError("DATABASE_URL must be PostgreSQL or a local SQLite file")
        for url in (self.metrics_url, self.logs_url, self.model_url, self.rules_url):
            parsed = urlparse(url)
            if url and (parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password):
                raise ValueError("Endpoint must be a configured HTTP(S) URL without embedded credentials")
            if parsed.hostname in {"api.openai.com", "chatgpt.com"}:
                raise ValueError("Use the approved internal model endpoint")
        if not self.model_url:
            raise ValueError("MODEL_CHAT_URL must point at an internal or demo server")
        queries = json.loads(Path(self.queries_file).read_text())
        if not isinstance(queries, dict) or not queries or any(not isinstance(v, str) for v in queries.values()):
            raise ValueError("QUERIES_FILE must contain a nonempty object of named query strings")
        query_count = len(queries)
        if self.lease_seconds < (query_count + 2) * self.query_timeout + self.model_timeout + 30:
            raise ValueError("JOB_LEASE_SECONDS is too short for the configured query budget")
        for key, value in {**self.label_map, **self.log_field_map}.items():
            if key not in self.scope_fields or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
                raise ValueError("Invalid scope label mapping")
