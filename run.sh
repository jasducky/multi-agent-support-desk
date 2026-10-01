#!/usr/bin/env bash
# run.sh: one place to start and reset everything for the customer support agent.
# Usage:
#   ./run.sh setup   once: create the `shop` database and the Toolbox's least-privilege login
#   ./run.sh reset   every test run: rebuild the tables and sample data (db/seed.sql)
#   ./run.sh toolbox start the MCP Toolbox (the three database tools) on port 5001
set -euo pipefail
cd "$(dirname "$0")"

DB=shop
ROLE=toolbox

case "${1:-}" in
  setup)
    # The Toolbox's database password lives in .env (git-ignored), made once and never printed.
    if ! grep -q '^TOOLBOX_DB_PASSWORD=' .env; then
      echo "TOOLBOX_DB_PASSWORD=$(openssl rand -hex 16)" >> .env
    fi
    PW=$(grep '^TOOLBOX_DB_PASSWORD=' .env | cut -d= -f2-)

    # The database, owned by you (the admin), not by the Toolbox.
    psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1 \
      || createdb "$DB"

    # The login: can connect and nothing else until db/seed.sql grants table rights.
    psql -d postgres -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$ROLE') THEN
    CREATE ROLE $ROLE LOGIN PASSWORD '$PW';
  ELSE
    ALTER ROLE $ROLE LOGIN PASSWORD '$PW';
  END IF;
END \$\$;
REVOKE ALL ON DATABASE $DB FROM PUBLIC;
GRANT CONNECT ON DATABASE $DB TO $ROLE;
SQL
    psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "REVOKE ALL ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO $ROLE;"
    echo "setup done: database '$DB', login '$ROLE' (password in .env)"
    ;;
  reset)
    psql -d "$DB" -v ON_ERROR_STOP=1 -q -f db/seed.sql
    echo "reset done: '$DB' rebuilt from db/seed.sql"
    ;;
  toolbox)
    # The MCP Toolbox on port 5001 (macOS AirPlay Receiver holds 5000). Runs until Ctrl+C.
    # tools.yaml reads ${TOOLBOX_DB_PASSWORD}, so it is passed in from .env here.
    TOOLBOX_DB_PASSWORD=$(grep '^TOOLBOX_DB_PASSWORD=' .env | cut -d= -f2-) \
      exec npx -y @toolbox-sdk/server@1.13.1 --config mcp_toolbox/tools.yaml --enable-api \
        --address 127.0.0.1 --port 5001 \
        --allowed-hosts localhost:5001,127.0.0.1:5001 --allowed-origins http://localhost,http://127.0.0.1
    ;;
  *)
    echo "usage: ./run.sh setup | reset | toolbox" >&2
    exit 1
    ;;
esac
