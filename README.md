# Self-Healing App — Daytona × Scalingo

A pricing service returns a real HTTP 500 for a quote with quantity zero. The orchestrator collects its correlated traceback, coordinates an isolated repair and shows the failing test, diff, and validation in a live dashboard. With cloud services configured, a human can authorize opening a GitHub pull request. Scalingo builds a Review App from that PR, and the orchestrator checks the preview before handing it to a reviewer.

## Run locally

Install Docker with Compose, or use Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 22+ with npm for the development servers. Local isolated repair uses a running Docker daemon.

```sh
cp .env.example .env
docker compose up --build
```

Open [the dashboard](http://localhost:3000). The orchestrator API is at [port 8000](http://localhost:8000/docs) and the pricing service is at [port 8001](http://localhost:8001/health).

For separate development servers, start these commands from the repository root in separate terminals:

```sh
uv sync --extra dev --extra daytona
uv run uvicorn main:app --app-dir apps/broken-app --port 8001 --no-access-log
```

```sh
uv run uvicorn healing.main:app --app-dir apps/orchestrator --port 8000
```

```sh
npm --prefix apps/dashboard install
npm --prefix apps/dashboard run dev
```

Check the original pricing service:

```sh
curl -i http://localhost:8001/health
curl -i 'http://localhost:8001/api/quote?quantity=5'
curl -i -H 'X-Correlation-ID: demo-zero' 'http://localhost:8001/api/quote?quantity=0'
```

The responses are HTTP 200, 200, and 500, respectively. The final response echoes `demo-zero`, which also appears in the JSON exception record. The development pricing server writes JSON lines to stdout and to `.data/broken-app.jsonl` by default. Compose shares the log file between the pricing service and the orchestrator.

Select **Trigger Incident** to run the workflow from the dashboard. The default `AGENT_MODE=fixture` uses a scripted fix and is labeled as simulated AI. In both local repair modes the HTTP failure and tests are real. To use model-generated repair locally, set `AGENT_MODE=openrouter` and `OPENROUTER_API_KEY` in `.env`, then restart the orchestrator. With `GITHUB_DRY_RUN=true`, the run stops with a validated diff at the publication stage. [OpenRouter setup](docs/openrouter-setup.md)

### Use Daytona with local staging

Keep the pricing service and its logs local while Daytona runs the repair against the actual GitHub base revision. Start the separate development servers above. In the orchestrator's `.env`, use:

```dotenv
DEMO_MODE=true
SANDBOX_PROVIDER=daytona
AGENT_MODE=openrouter
GITHUB_OWNER=svngoku
GITHUB_REPOSITORY=daytona-scalingo-self-healing-app
GITHUB_DEFAULT_BRANCH=main
GITHUB_ALLOWED_REPOSITORIES=svngoku/daytona-scalingo-self-healing-app
GITHUB_DRY_RUN=true
GITHUB_WRITE_ENABLED=false
BROKEN_APP_URL=http://127.0.0.1:8001
```

Set `DAYTONA_API_KEY` and `OPENROUTER_API_KEY` with your existing server-side credentials. A `GITHUB_TOKEN` is optional for reading this public repository. Run local staging from the same buggy revision as the configured branch, then restart the orchestrator and trigger an incident. It resolves the branch to a real commit SHA and Daytona checks out that SHA. The dashboard can show the validated diff and sandbox cleanup. Publication still requires [live configuration](#run-with-cloud-services) and incident-specific authorization. [Public demo repository](https://github.com/svngoku/daytona-scalingo-self-healing-app)

A hosted Daytona sandbox completed an OpenRouter repair from local staging and was destroyed after validation. [Daytona dry-run evidence](docs/validation.md#hosted-daytona-with-local-staging)

## Dashboard design

The dashboard uses [UI SDK React](https://ui-sdk.dev/docs/react) primitives for buttons, tabs, dialogs, selection, and input controls, with React Flow for the incident graph. UI SDK React and Core are pinned to `0.1.0-beta.6`.

The visual system uses self-hosted ABC Favorit Regular headings, IBM Plex Sans interface text, warm surfaces, orange primary actions, and restrained outlines. Cyan identifies sandbox execution, violet identifies Scalingo deployment, and green and red communicate outcomes. The header's **Light theme** toggle saves the preference in the browser. Dark is the default. [Scalingo reference](https://scalingo.com/fr/) · [Reusable demo design guide](docs/design.md)

## Run with cloud services

- **Daytona** provisions the sandbox and checks out the incident commit from the configured public GitHub demo repository. Set `DAYTONA_API_KEY` in the orchestrator environment. [Daytona setup](docs/daytona-setup.md)
- **OpenRouter** diagnoses and proposes edits through its OpenAI-compatible Responses endpoint, using the OpenAI Python client. Set `OPENROUTER_API_KEY` and choose a compatible model in `OPENROUTER_MODEL`. [OpenRouter setup](docs/openrouter-setup.md)
- **GitHub** stores the patch in a branch and pull request. Set `GITHUB_OWNER`, `GITHUB_REPOSITORY`, and `GITHUB_DEFAULT_BRANCH`. Publishing also requires a repository-scoped `GITHUB_TOKEN`, the explicit write setting, and per-incident authorization after validation. [GitHub setup](docs/github-setup.md)
- **Scalingo** hosts the intentionally broken staging app and its PR previews. Set `SCALINGO_API_TOKEN`, `SCALINGO_APP_NAME`, and the regional `SCALINGO_API_URL`. Configure its GitHub integration and enable Review Apps on staging. [Scalingo setup](docs/scalingo-setup.md)

Set the following in the orchestrator's `.env`, alongside the provider variables above:

```dotenv
DEMO_MODE=false
SANDBOX_PROVIDER=daytona
AGENT_MODE=openrouter
GITHUB_DRY_RUN=false
GITHUB_WRITE_ENABLED=true
GITHUB_ALLOWED_REPOSITORIES=your-owner/your-demo-repo
ORCHESTRATOR_API_TOKEN=replace-with-a-long-random-token
BROKEN_APP_URL=https://your-staging-app.osc-fr1.scalingo.io
```

Enter the same orchestrator token in dashboard Settings. For a local dashboard connected to live providers, use the separate development-server commands above. The Compose file is wired to the local demo staging service. Use the same demo base commit for the running staging deployment and the configured GitHub branch. Keep the orchestrator on a trusted machine and its provider credentials out of the staging environment.

## Tests

```sh
uv run --extra dev pytest
uv run --extra dev pytest apps/broken-app/tests -q
RUN_DOCKER_TESTS=1 uv run --extra dev pytest -m docker
```

The second command has one expected failure on the original checkout. Its zero-quantity regression expects HTTP 400 with a validation message. The third command runs the local fixture workflow in Docker and requires a running Docker daemon. For opt-in, read-only GitHub and Scalingo checks with live configuration, run `RUN_LIVE_TESTS=1 uv run --extra dev --extra daytona pytest tests/test_live.py -q`. See [validation results](docs/validation.md) for the evidence captured locally and the cloud checks still pending.

## Project layout

| Directory | Role |
| --- | --- |
| `apps/dashboard` | Next.js incident dashboard |
| `apps/orchestrator` | FastAPI state machine, provider adapters, SQLite and SSE |
| `apps/broken-app` | Standalone pricing service, regression tests, Scalingo build configuration |
| `packages/shared` | Shared workflow contracts |
| `tests` | Orchestrator and integration tests |

[Architecture](docs/architecture.md) · [Design guide](docs/design.md) · [10-minute demo script](docs/demo-script.md)
