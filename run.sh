#!/usr/bin/env bash
# run.sh: one place to start and reset everything for the customer support agent.
# Usage:
#   ./run.sh setup    once: create the `shop` database and its two least-privilege logins
#   ./run.sh reset    every test run: rebuild the tables and sample data (db/seed.sql)
#   ./run.sh toolbox  start the MCP Toolbox (the database tools) on port 5001
#   ./run.sh chat     Stage 3's bare chat loop in the terminal (needs the Toolbox running)
set -euo pipefail
cd "$(dirname "$0")"

DB=shop

# Read one value from .env without printing it.
env_value() { grep "^$1=" .env | cut -d= -f2-; }

# Create (or update) a database login whose password lives in .env, made once, never printed.
# It can connect and nothing else until db/seed.sql grants table rights.
make_login() {
  local role=$1 var=$2 pw
  grep -q "^$var=" .env || echo "$var=$(openssl rand -hex 16)" >> .env
  pw=$(env_value "$var")
  psql -d postgres -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$role') THEN
    CREATE ROLE $role LOGIN PASSWORD '$pw';
  ELSE
    ALTER ROLE $role LOGIN PASSWORD '$pw';
  END IF;
END \$\$;
GRANT CONNECT ON DATABASE $DB TO $role;
SQL
  psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "GRANT USAGE ON SCHEMA public TO $role;"
}

case "${1:-}" in
  setup)
    # The database, owned by you (the admin), not by either login.
    psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1 \
      || createdb "$DB"
    psql -d postgres -v ON_ERROR_STOP=1 -q -c "REVOKE ALL ON DATABASE $DB FROM PUBLIC;"
    psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "REVOKE ALL ON SCHEMA public FROM PUBLIC;"

    make_login toolbox TOOLBOX_DB_PASSWORD          # the agent's three tools
    make_login login_checker LOGIN_DB_PASSWORD      # the log-in check only
    echo "setup done: database '$DB', logins 'toolbox' and 'login_checker' (passwords in .env)"
    ;;
  reset)
    psql -d "$DB" -v ON_ERROR_STOP=1 -q -f db/seed.sql
    echo "reset done: '$DB' rebuilt from db/seed.sql"
    ;;
  toolbox)
    # The MCP Toolbox on port 5001 (macOS AirPlay Receiver holds 5000). Runs until Ctrl+C.
    # tools.yaml reads both database passwords, so they are passed in from .env here.
    TOOLBOX_DB_PASSWORD=$(env_value TOOLBOX_DB_PASSWORD) \
    LOGIN_DB_PASSWORD=$(env_value LOGIN_DB_PASSWORD) \
      exec npx -y @toolbox-sdk/server@1.13.1 --config mcp_toolbox/tools.yaml --enable-api \
        --address 127.0.0.1 --port 5001 \
        --allowed-hosts localhost:5001,127.0.0.1:5001 --allowed-origins http://localhost,http://127.0.0.1
    ;;
  chat)
    exec .venv/bin/python -m support.cli_bare
    ;;
  *)
    echo "usage: ./run.sh setup | reset | toolbox | chat" >&2
    exit 1
    ;;
esac
