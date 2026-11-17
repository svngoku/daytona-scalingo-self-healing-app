# Validation

## Verified locally

| Check | Result |
| --- | --- |
| Python 3.12 and provider dependencies | `uv sync --python 3.12 --extra dev --extra daytona` completed. |
| Standard Python suite | 59 passed. The Docker and live-provider opt-ins were skipped. Coverage includes OpenRouter transport, structured output, conversation replay, argument validation, tool limits, and repair retries. |
| Original pricing service | Health and quantity 5 returned HTTP 200. Quantity 0 returned HTTP 500. Its correlation ID matched a JSON log containing the `ZeroDivisionError` traceback. The standalone suite had two passes and the expected zero-quantity failure. |
| Real Docker repair | The original regression failed inside the sandbox. After the scripted fixture applied its edit, the regression and all three pricing tests passed. The orchestrator captured the diff, removed the sandbox, and recorded the dry run at `PR_CREATING`. The host pricing source stayed deliberately broken. |
| Real OpenRouter repair | Incident `596de22fdaa74e1d` used `openai/gpt-5-mini` through OpenRouter with `simulated=false`. Diagnosis succeeded, Docker reproduced the failure, model tool calls edited the isolated source, and the regression and full pricing suite passed within one repair attempt. The sandbox was destroyed and publication remained `dry_run` at `PR_CREATING`. No GitHub write or Review App deployment occurred. Local evidence is in `.data/openrouter-validation.json`. |
| Compose backend | The pricing and orchestrator images built. The same repair passed in the built orchestrator using the shared JSON log volume and a disposable Docker sandbox. |
| Dashboard checks | TypeScript and the Next.js production build passed. Chromium verified desktop and 390px mobile layouts, graph controls, and navigation. Triggering an incident from the dashboard connected the event stream and displayed the Docker dry run's terminal output, diff, tests, and report. The completed event history and evidence loaded again after refresh. |
| Light and dark themes | Browser checks passed on desktop and mobile. The header toggle switches the dashboard and graph to the selected theme, and the browser restores the selection after refresh. |
| UI SDK and fonts | UI SDK keyboard tabs, selection, dialog focus and dismissal, authorization payloads, rejected-action recovery, and token controls were checked. Mutation checks used intercepted browser requests. Chromium loaded the supplied ABC Favorit Regular WOFF2 and IBM Plex Sans locally. |
| Python lint | Ruff passed for the orchestrator, tests, and pricing service. |

In fixture runs, the fixture supplies the proposed edit. HTTP requests, logs, tests, diff extraction, and sandbox cleanup are executed locally. The separate OpenRouter run used actual model-generated edits. Its first routing failure exposed an unsupported optional `parallel_tool_calls` parameter; the corrected request passed a bounded live tool-call probe and the complete local repair. The application enforces the tool-call limit itself.

```sh
uv sync --python 3.12 --extra dev --extra daytona
uv run --extra dev pytest -q
uv run --extra dev ruff check apps/orchestrator tests apps/broken-app
RUN_DOCKER_TESTS=1 uv run --extra dev pytest -m docker
docker compose build orchestrator broken-app
npm --prefix apps/dashboard run typecheck
npm --prefix apps/dashboard run build
```

## Hosted verification pending

The standard suite uses mocks for provider calls. OpenRouter was separately verified with the local Docker workflow above. GitHub authenticated as `svngoku`, the public demo repository was created, and a Daytona sandbox-list request succeeded. The [Daytona repair with local staging](../README.md#use-daytona-with-local-staging) still needs a full run against the pushed base revision. Incident PR publication and Scalingo Review App validation also remain pending. Use the [live configuration](../README.md#run-with-cloud-services) with a linked Scalingo staging deployment and Review Apps enabled. [Public demo repository](https://github.com/svngoku/daytona-scalingo-self-healing-app)

The opt-in live test reads the Scalingo app and GitHub base revision. The full rehearsal additionally checks that Daytona reproduces and repairs the failure, explicit publication opens the incident PR, and the deployed Review App returns HTTP 400 for quantity zero before the dashboard shows human review.

```sh
RUN_LIVE_TESTS=1 uv run --extra dev --extra daytona pytest tests/test_live.py -q
```
