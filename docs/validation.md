# Validation

## Verified locally

| Check | Result |
| --- | --- |
| Python 3.12 and provider dependencies | `uv sync --python 3.12 --extra dev --extra daytona` completed. |
| Standard Python suite | 62 passed and two opt-in checks skipped. Coverage includes OpenRouter transport, structured output, conversation replay, argument validation, tool limits, and repair retries. |
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

## Hosted Daytona with local staging

Incident `5e148b120c504cbd` started from the real local pricing failure. Daytona checked out base commit `5af2d6554da762dc11874a9fe821bcedcc47c118` from the public GitHub repository. OpenRouter generated the repair, and the regression and full pricing suite passed on the third attempt. Daytona sandbox `5fd690a2-436b-480e-89c0-6d0926c32c25` was destroyed. The incident stopped at `PR_CREATING` with publication in `dry_run`. Evidence is recorded in the local, Git-ignored file `.data/daytona-validation.json`. [Public demo repository](https://github.com/svngoku/daytona-scalingo-self-healing-app)

The hosted run exposed repeated rejection of grouped tool calls and a retry that attempted to report a retained patch. The subsequent changes process independent calls in order under a total limit of 12 calls and 12 rounds per attempt, and allow a retry to report a sandbox-confirmed patch after inspecting it again. The updated behavior passed offline tests. A new hosted run after those changes is unverified.

## Publication verification pending

Incident PR publication and Scalingo Review App verification remain pending. The opt-in live test reads the Scalingo app and GitHub base revision. The [full rehearsal](../README.md#run-with-cloud-services) requires a Scalingo staging app linked to the GitHub repository with Review Apps enabled. It then checks that explicit publication opens the incident PR and the deployed Review App returns HTTP 400 for quantity zero before the dashboard shows human review.

```sh
RUN_LIVE_TESTS=1 uv run --extra dev --extra daytona pytest tests/test_live.py -q
```
