# Scalingo staging and Review Apps

1. Create a dedicated staging app in your chosen Scalingo region. In its environment, set `PROJECT_DIR=apps/broken-app`. Scalingo builds only that directory. It contains `requirements.txt` for Python buildpack detection, `.python-version` for Python 3.12, and a `Procfile` that binds Uvicorn to the supplied `PORT`. The included Dockerfile is for local use. [Monorepo builds](https://doc.scalingo.com/platform/app/monorepo) · [Python buildpack](https://doc.scalingo.com/languages/python/start)
2. Connect GitHub in your Scalingo account settings. In the staging app's **Deploy → Configuration**, link the configured GitHub repository and select the demo base branch. Deploy the deliberately broken base commit manually for the first rehearsal, then check that staging returns HTTP 200 from `/health` and 500 from `/api/quote?quantity=0`. [Deploy with GitHub](https://doc.scalingo.com/platform/deployment/deploy-with-github)
3. In the staging app's **Review Apps** configuration, enable automatic deployment on pull request creation. Leave review deployments from forks disabled for this demo. Review Apps inherit staging environment variables, including `PROJECT_DIR`. Keep provider keys and production data out of the staging app and its previews. [Review Apps](https://doc.scalingo.com/platform/app/review-apps)
4. Create an API token from your Scalingo profile. Set `SCALINGO_API_TOKEN`, `SCALINGO_APP_NAME`, and `SCALINGO_API_URL` in the orchestrator's `.env`. For the Paris region, the API origin is `https://api.osc-fr1.scalingo.com`. For Paris SecNumCloud, use `https://api.osc-secnum-fr1.scalingo.com`. The adapter exchanges the API token for a short-lived bearer token. [Scalingo API authentication](https://developers.scalingo.com/#authentication)
5. Configure the orchestrator's target URL with the staging HTTPS origin. The pricing service writes a JSON record to stdout for each request. The adapter reads the application logs and looks for the incident correlation ID. [Scalingo application logs API](https://developers.scalingo.com/logs)
6. After the incident PR is open, find its child app in Scalingo and watch the deployment state in the dashboard. The orchestrator contacts the preview once its deployment is ready. Keep the rehearsal preview accessible to the orchestrator for its smoke checks.

### Troubleshooting

| Symptom | Check |
| --- | --- |
| Buildpack cannot detect Python | `PROJECT_DIR` points to `apps/broken-app` and the commit contains the app's `requirements.txt`. |
| HTTP 500 has no matching log | Verify the app name, region and target URL. Check that staging's web stdout contains the JSON event with the same correlation ID. |
| No Review App appears | Verify the staging integration points to the PR repository, automatic Review Apps are enabled, and the PR originates inside the repository. |
| Review App deploys but smoke fails | Inspect the child build and runtime logs, verify that the preview has the repair commit, and check reachability from the orchestrator. |
| Staging shows HTTP 400 before the incident | Staging already has a fix. For a rehearsal, deploy a dedicated demo branch whose baseline still contains the intentional bug. |
