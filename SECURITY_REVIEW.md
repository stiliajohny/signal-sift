# Security review notes

This document describes the implemented pilot and its boundaries so the security team can inspect concrete code and configuration. It is not a certification or a claim that the deployment has passed a security assessment.

## Trust boundaries and data flow

| Boundary | Data and implemented handling | Files to review |
|---|---|---|
| Alertmanager → API | Bearer-authenticated JSON; 1 MB body cap; max 200 alerts; validated timestamp/metadata shapes; response after transaction commit | `api.py`, `models.py` |
| API/worker → Postgres | Bound query parameters; database transactions; incident and lease locks; separate reporting views | `storage.py`, `postgres-init.sh` |
| Worker → metrics/rules/logs | Explicit configured URLs; scoped queries; bearer auth; no automatic redirects/proxy env; HTTPS verification; per-request timeouts and 1 MB response caps | `config.py`, `clients.py` |
| Evidence → model | Heuristic redaction, bounded samples/log lines, character budget; logs/alerts framed as untrusted data; no executable tools | `clients.py`, `models.py` |
| Local model acquisition → Ollama | One-shot model pull; persistent local weights; cloud disabled; no cloud model tag | `compose.yaml` |
| Model response → storage/dashboard | JSON/schema validation; reject unknown evidence IDs/incomplete responses; current-revision assessment only; original severity retained | `models.py`, `clients.py`, `storage.py` |
| Grafana → database | Separate login; `SELECT` on reporting views; no grants to evidence/payload tables | `postgres-init.sh`, datasource YAML, `storage.py` |
| Operator → demo controls | Simulator controls are unauthenticated but published only on localhost; entirely synthetic fixtures | `demo.py`, `compose.yaml` |

File references under Python refer to `src/alert_insight`. All source/destination endpoints are operator-selected; generator URLs in webhook input are never followed.

## Data retained

Postgres stores scope identifiers and severity, episode payloads, unique event records, webhook receipt counters, evidence snapshots (sampled metrics and log content), model outputs/version marker, review reports and free-text feedback. Credentials are not intentionally stored in those tables. The initial schema uses JSON serialized into text; evidence views are deliberately not granted to Grafana.

Model prompts contain the collected evidence. The default uses local Ollama; work mode can use the explicitly configured internal serving endpoint. That endpoint's access logs, prompt retention and infrastructure need independent review. `OLLAMA_NO_CLOUD=1` disables cloud features; it is not a firewall or proof of zero network traffic. The initial model download contacts a registry. No external model API is called by default.

## Credentials and authentication

`scripts/init_env.py` creates independently generated credentials and writes `.env` mode `0600`; `.env` is excluded from Git, the Docker build context and the delivered archive. `*_FILE` is supported by the Python secret loader for mounted credentials. No real employer secret has been requested, added or inspected.

The pilot API uses one shared bearer token and constant-time comparison. Authenticated endpoints are webhook ingestion, incident list/detail, feedback and reviews. Liveness, DB readiness and queue-count metrics do not require a token. The same bearer credential can read incidents and write feedback; there is **no user identity, per-user RBAC, feedback author audit or per-route token separation** yet. Restrict its audience and add your existing SSO/service identity boundary before production exposure.

Default backend services load `.env`, so container environments contain more pilot settings/credentials than each process needs. Treat Docker administrator/container-inspection access as privileged. For production use purpose-specific mounted secrets and minimal per-service environment configuration. The simulator intentionally does not inherit backend credentials. Grafana's DB credential is separate and read-only on the application reporting views.

The generated webhook token is owned by root/group `65534` with mode `0440` when provisioning runs as root, so Alertmanager's service identity can read it. The local demo shares generated monitoring configuration between Prometheus and Alertmanager; both run within that trusted demo network and can potentially read the token through the shared mount. Separate the config/secret mounts in a hardened deployment. Do not copy rendered monitoring-config volumes into a public repository.

## Database privilege and availability

The demo Postgres `app` user is created by the official image and is a **superuser**; this simplifies initial schema and read-role creation. This is not the recommended production runtime privilege. Split a migration owner from restricted API/worker roles, remove unnecessary superuser rights, protect backup access and require database TLS for off-host deployments. Grafana has schema usage and read-only view access, not mutation permissions. The current read views include model-generated incident summaries, so those can still reveal operational information.

The queue uses leases and unique claim tokens, with up to three attempts and capped backoff. PostgreSQL `SKIP LOCKED` permits independent claims. Ingestion serializes incident creation with a transaction-scoped advisory lock; this trades throughput for simple pilot correctness. Results for stale revisions remain historical rather than replacing the current incident brief. Existing paging integrations are outside this queue and must remain independent when adding the analysis route.

The schema initializer is idempotent for this initial schema, not a versioned upgrade/rollback system. No high-availability database configuration, backup orchestration or automatic retention deletion is supplied. Define retention, encryption at rest, recovery and deletion policies before sensitive telemetry is ingested. Docker named volumes preserve data but are not backups.

## Outbound access and injection boundaries

Configured URLs are validated as HTTP(S), with no embedded basic-auth credentials. Requests do not follow redirects and do not honor proxy environment variables implicitly. Alert-supplied URLs are never fetched. However, configured endpoints are not constrained by a DNS/IP allowlist, and operator configuration can still target arbitrary networks. Apply actual egress network rules and approved TLS endpoints; URL validation is not an SSRF/egress policy by itself.

Canonical scope names are fixed. Mapped label names are identifier-validated. Query placeholder values are quoted with JSON escaping; scoped subset placeholders fail on missing required values. Query templates themselves are trusted operator configuration and must be reviewed. Selecting incomplete scopes can mix clusters/tenants if the operator omits those matchers. LogsQL and Loki adapters are separate, and tenant headers are explicitly configured.

SQL values use bound parameters. The only interpolated database role name is restricted to identifier syntax. The demo Grafana reporting queries are provisioned read-only; avoid broadening database grants when adding panels.

Redaction matches common secret-bearing field names and simple key/value patterns. It is **not comprehensive DLP**: unlabelled secrets, bearer strings in free text, URLs, unusual encodings and PII can escape it. Source-side filtering and an approved redaction policy are needed before production model access. Worker error messages log exception classes and incident IDs, not full payloads/credentials.

Alerts, logs and model output are untrusted. The system prompt directs the model to treat source content as data, but prompting alone cannot guarantee resistance to prompt injection. The model has no tool execution and cannot alter rules or silence alerts through this app. JSON validation constrains structure, and evidence-ID validation prevents nonexistent IDs; neither checks whether an interpretation or cited fact is true. Keep recommendations advisory and evaluate on human-labelled history.

## Containers and exposure

Python long-running processes use UID `10001`; configuration generation runs as root to write its shared volume and token ownership. Ollama runs with the vendor image defaults and uses its own persistent volume. External images use explicit version tags, not immutable digests. Python runtime packages are version-pinned in `requirements.lock`, but there are no wheel hashes, generated SBOM or vulnerability-scan results. Build isolation/setuptools and base image layers also require review. No claim of a CVE-clean supply chain is made.

Published interfaces bind to `127.0.0.1`. Postgres has no host port. Grafana anonymous signup is disabled and its administrator password is generated. Analytics reporting/update checks are disabled. The local demo uses HTTP/database SSL disabled inside its Compose network. This is a trusted local development assumption, not transport security for a remote environment.

The Ollama API has no application auth in this configuration. It is reachable by local host processes and Compose peers, and can consume CPU/RAM through requests. Do not expose port 11434 publicly; use your authenticated reverse proxy/service boundary if remote access is needed. Only one model/request parallelism is configured to reduce contention, not to implement rate limiting.

No rate limiter, request concurrency cap, network segmentation, audit export, per-user incident access, or authenticated simulator control has been implemented. Observability endpoints should not be exposed through a public ingress alongside the API. Use existing organisation controls for production ingress/egress and service identity.

## Reviewable next deployment steps

Before connecting live telemetry, replace demo database privileges, provide TLS/service identity and scoped read credentials, decide source/model data handling and retention, limit outbound endpoints, separate mounted secrets, and validate the real APIs and model budget/accuracy. Preserve paging recipients when adding the analysis route. These are identified pilot boundaries, not new approval gates in the implementation workflow.

`VALIDATION.md` records what was actually checked. No Docker daemon, PostgreSQL runtime or Ollama model execution was available in the authoring environment; this documentation does not assert those checks passed.
