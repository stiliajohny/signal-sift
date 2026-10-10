# Verification record

Date: 2026-10-10. This is a record of authoring checks, not a claim of production certification or real-model accuracy.

## Passed

- Python compilation/AST parsing for the source modules and helper scripts.
- Authored Compose/provisioning YAML and dashboard/query JSON parsed successfully.
- PostgreSQL table/index/view schema statements parsed with a PostgreSQL parser, including the dialect-specific `CREATE OR REPLACE VIEW` and `STRING_AGG` transformations.
- Dashboard panel SQL parsed after replacing Grafana time macros with representative SQL expressions.
- One-off smoke flow using the real FastAPI app, real worker/collector/storage code, a temporary SQLite database, and HTTP mocks/simulator fixtures: missing bearer → 401; malformed webhook → 422; oversized webhook → 413; valid webhook → committed 202; duplicate notification → no duplicate episode.
- Worker supplied Ollama schema-constrained request fields, parsed/validated a mocked final response, stored evidence and priority, and retained original alert severity/model identifier.
- A result computed before a new incident revision did not become the current brief; the job was requeued and a later resolution processed.
- Feedback insertion, scheduled review persistence and a distinct later episode were exercised.
- VictoriaLogs and Loki request/response adapters, Loki tenant header/nanosecond bounds, query value escaping, and the internal Chat Completions adapter were exercised with mocked HTTP responses.
- Generated Prometheus, alert-rule and Alertmanager YAML parsed successfully.

No new test suite is included, following the request. These were one-off authoring checks. The current Starlette TestClient emitted an httpx deprecation warning; that concerns the one-off check client, not an exercised server failure.

## Not verified here

- Docker Compose schema/interpolation via the Docker CLI, image pulls/builds, dependency installation inside the Docker image, real service startup or inter-container network access. Docker is not installed in this environment.
- Actual PostgreSQL execution, privilege enforcement or PostgreSQL concurrency under load. Schema parsing and SQLite execution are not substitutes for those checks.
- Real Ollama model download, model support/latency, memory use, generation quality or schema adherence on hardware. The smoke response was explicitly mocked. Source research confirmed the selected named tag and the serving API documentation, not an inference benchmark.
- Mounted webhook-token ownership/group access under Docker. The authoring filesystem rejected ownership changes; that operation was substituted only for the one-off config-generation check. The delivered Docker provisioner still applies ownership/group permissions normally.
- Grafana rendering, state-timeline/annotation visual correctness, data source connection or effective database grants.
- Real VictoriaMetrics/VictoriaLogs/Loki/rule-engine endpoints and organisation-specific labels/tenancy/auth; no production credentials were used.
- GPU override execution, image digests, dependency hash validation, vulnerability scanning, backup/recovery, retention jobs or security-team acceptance.

## On-host end-to-end check

Run the README startup commands, confirm all running services are healthy/started and one-shot setup services exited successfully, and inspect the model-pull logs. Set `persistent`, wait for the configured alert evaluation/grouping/model latency, and verify:

1. Prometheus shows the demo alert firing and Alertmanager receives it.
2. The API contains a recorded incident and the worker stores an assessment/evidence.
3. Grafana shows the incident, original severity, model identity, episode/chart annotation and review results.
4. Set `healthy`; the producer sends a resolved notification, the same episode resolves, and the incident reflects the latest revision.
5. Existing production paging remains independent when adding an analysis receiver later.

Until those steps run on an actual Docker host, describe this deliverable as implemented with local smoke checks, **not verified end to end**.

## Branding update

SignalSift names in Compose, API metadata, dashboard UID/title and README were checked for consistency. Python compilation passed after the update. The generated logo was visually inspected and verified as a valid transparent RGBA PNG, and the repository-relative README image reference exists. This adds no Docker or live-model runtime verification.
