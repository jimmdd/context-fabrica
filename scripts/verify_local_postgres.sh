#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 -f sql/postgres_bootstrap.sql
psql -v ON_ERROR_STOP=1 -f sql/postgres_smoke_test.sql
