#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=grafana_password="$GRAFANA_DB_PASSWORD" <<'SQL'
CREATE ROLE grafana_reader LOGIN PASSWORD :'grafana_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
