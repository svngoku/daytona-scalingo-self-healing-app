# Daytona setup

1. Create a Daytona API key under your organization's API Keys page. Make sure the key can provision, access, and remove sandboxes in the organization. Store it as `DAYTONA_API_KEY` in the orchestrator environment. [Daytona API keys](https://www.daytona.io/docs/api-keys)
2. From the repository root, run `uv sync --extra dev --extra daytona`. The adapter uses the official Python SDK. [Daytona Python SDK](https://www.daytona.io/docs/en/python-sdk/)
3. Configure the public GitHub demo repository and base branch in `.env`. Push the intentionally broken pricing commit to that branch before starting the rehearsal. The sandbox needs read access to the repository and the package index used by the Python installer.
4. Set `AGENT_MODE=openrouter` and `SANDBOX_PROVIDER=daytona` in `.env`. Use [Daytona with local staging](../README.md#use-daytona-with-local-staging) for a publication dry run, or [live settings](../README.md#run-with-cloud-services) for Scalingo staging and authorized PR publication. The adapter blocks outbound access after checkout and dependency installation. Check that your Daytona organization can apply per-sandbox network settings.
5. Trigger an incident and watch for the sandbox ID, checkout, baseline failure, patch attempt and test output. After execution, inspect the reported sandbox cleanup status.

Keep `GITHUB_TOKEN`, `OPENROUTER_API_KEY`, and `SCALINGO_API_TOKEN` in the orchestrator. The Daytona process needs the public clone URL and commit, with no write credentials.

### Troubleshooting

- **Provisioning fails.** Check the organization, API key permissions, current quotas, and Daytona rate limits. [Daytona troubleshooting](https://www.daytona.io/docs/en/troubleshooting/)
- **Checkout fails.** Ensure the configured commit exists in the public repository and the sandbox can reach GitHub.
- **Package installation times out.** Confirm the organization's sandbox outbound policies allow access to the required repository and package hosts. [Daytona network limits](https://www.daytona.io/docs/en/network-limits/)
- **Cleanup fails.** Use the incident's sandbox ID to locate the sandbox in Daytona and remove it after confirming the run has stopped.
