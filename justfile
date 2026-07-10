# Start the development server : just dev
dev:
    uv run python -m app.server

# Start the background worker for document ingestion tasks
worker:
    uv run arq worker.doc_ingestion_worker.WorkerSettings

# Auto-generate a new database migration
# Usage: just migration "added users table"
migration msg="auto":
    uv run alembic revision --autogenerate -m "{{msg}}"

# Run all pending migrations : just migrate
migrate:
    uv run alembic upgrade head

# Run seeders : just seed
seed:
    uv run python scripts/seed.py

# Format code using ruff : just format
format:
    uv run ruff check . --fix
    uv run ruff format .

# Run sonarqube analysis
sonar:
    uv run pysonar \
        --sonar-host-url=http://localhost:9000 \
        --sonar-token=sqp_3b7feae1c57bc659f215f0696cc15e348ac6a615 \
        --sonar-project-key=automation-agent

# Check code without modifying (useful for CI)
lint:
    uv run ruff check .
    uv run ruff format --check .
