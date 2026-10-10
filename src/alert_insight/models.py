import hashlib
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def redact(value: object) -> object:
    if isinstance(value, dict):
        return {k: "[redacted]" if re.search(r"password|token|authorization|secret|cookie", k, re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"(?i)\b(password|token|secret|authorization)\s*[:=]\s*\S+", r"\1=[redacted]", value)[:4000]
    return value


class Alert(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str = ""
    fingerprint: str = ""

    @field_validator("startsAt", "endsAt")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Alert timestamps must include a timezone")
        return value

    @field_validator("labels", "annotations")
    @classmethod
    def bounded_strings(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 100 or any(len(k) > 256 or len(v) > 4000 for k, v in value.items()):
            raise ValueError("Alert metadata exceeds limits")
        return value

    def episode_key(self) -> str:
        # Use labels, not a possibly absent/untrusted external fingerprint.
        return digest([self.labels, self.startsAt.isoformat()])

    def event_key(self) -> str:
        # Firing EndsAt is a refresh deadline, not a new occurrence.
        return digest([self.episode_key(), self.status,
                       self.endsAt.isoformat() if self.status == "resolved" and self.endsAt else None,
                       self.annotations])


class Notification(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: str = "4"
    receiver: str = ""
    groupKey: str = ""
    status: Literal["firing", "resolved"]
    alerts: list[Alert] = Field(min_length=1, max_length=200)
    truncatedAlerts: int = Field(default=0, ge=0)


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: Literal["urgent", "investigate", "transient", "unknown"]
    summary: str = Field(min_length=1, max_length=500)
    explanation: str = Field(min_length=1, max_length=3000)
    suspected_cause: str | None = Field(default=None, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1, max_length=30)
    missing_evidence: list[str] = Field(default_factory=list, max_length=30)
    next_checks: list[str] = Field(default_factory=list, max_length=20)
