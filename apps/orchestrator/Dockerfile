FROM python:3.12-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends docker.io && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY pyproject.toml ./
COPY apps/orchestrator ./apps/orchestrator
COPY apps/broken-app ./apps/broken-app
RUN pip install --no-cache-dir '.[daytona]'
EXPOSE 8000
CMD ["uvicorn", "healing.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
