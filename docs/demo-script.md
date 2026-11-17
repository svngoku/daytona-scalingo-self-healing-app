# 10-minute live demo

## Before presenting

Choose either the full cloud path or a local rehearsal. For the cloud path, confirm the public GitHub demo base commit matches the staging deployment, automatic Scalingo Review Apps are enabled, and the Daytona and OpenRouter keys are configured. Verify dashboard and orchestrator access, staging health, and that the zero-quantity quote still returns 500. Open the Scalingo Review Apps page and the demo GitHub repository in separate tabs.

The local rehearsal shows the real request, logs, sandbox test failure, diff and passing tests. If using the scripted repair fixture, point out its label before starting. Finish the rehearsal with the dry-run evidence.

## Run of show

| Time | Show | Say |
| --- | --- | --- |
| 0:00–1:00 | Dashboard and a healthy staging app | “This health check tells us the pricing service is reachable. A customer can still hit an error on a specific quote.” |
| 1:00–2:00 | **Trigger Incident**, then the HTTP 500 and matching log | “The request and the traceback carry the same correlation ID. We can follow this one failure through the workflow.” |
| 2:00–4:00 | Diagnosis and sandbox lifecycle | “The orchestrator coordinates the run. Daytona gives it a clean workspace at the staging commit. The first test reproduces the error there.” |
| 4:00–6:00 | Repair diff and test results | “The patch validates quantity before the calculation. The zero-quantity regression now passes, and the ordinary quote still works.” |
| 6:00–7:30 | Authorize publishing and open the PR | “I’m authorizing the validated commit on an incident branch. The PR carries the diagnosis and the test evidence.” |
| 7:30–9:00 | Scalingo Review App state and smoke checks | “Scalingo builds and hosts the preview from the PR. The orchestrator can check the preview only after it’s reachable.” |
| 9:00–10:00 | Preview URL, HTTP 400 and human review state | “The preview returns HTTP 400 with a quantity validation message. The branch is now ready for a reviewer to decide whether it should merge.” |

For a local rehearsal, use the last four minutes to compare the original failing output with the passing repair, inspect the diff, and show where GitHub and Scalingo would enter the live workflow.

If a live preview build takes longer than planned, show the currently reported state and the PR's verified test evidence. When the preview is reachable, run the two pricing checks against its origin:

```sh
curl -i "${PREVIEW_URL}/api/quote?quantity=5"
curl -i "${PREVIEW_URL}/api/quote?quantity=0"
```

Expect HTTP 200 for an ordinary quote and HTTP 400 for zero. End with the PR open for human review.
