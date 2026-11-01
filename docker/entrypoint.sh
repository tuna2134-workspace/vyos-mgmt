#!/bin/sh
set -eu

# Apply migrations before accepting traffic. Safe to run repeatedly and with
# multiple replicas in the common case (Alembic takes a lock on the version
# table); for large fleets run migrations as a separate job instead.
alembic upgrade head

exec vyos-mgmt serve --host 0.0.0.0 --port "${PORT:-8000}"
