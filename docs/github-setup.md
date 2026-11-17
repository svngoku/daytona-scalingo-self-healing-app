# GitHub setup

1. Publish a dedicated public demo repository so Daytona can clone it without credentials. Push this monorepo with the deliberate HTTP 500 on the configured base branch. Use the same repository and branch for the Scalingo staging integration.
2. Set `GITHUB_OWNER`, `GITHUB_REPOSITORY`, and `GITHUB_DEFAULT_BRANCH` for the orchestrator. Put the full `owner/repo` in `GITHUB_ALLOWED_REPOSITORIES`. Restrict repair to repositories you control and keep each demo instance scoped to its configured repository.
3. For live publishing, create a fine-grained personal access token scoped to the demo repository, with **Contents: Read and write** and **Pull requests: Read and write**. Store it as `GITHUB_TOKEN` in the orchestrator environment. Check any organization approval requirements for the token before the demo. [Git commits API permissions](https://docs.github.com/en/rest/git/commits#create-a-commit) · [Pull requests API permissions](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request)
4. For live publishing, set `GITHUB_WRITE_ENABLED=true` and `GITHUB_DRY_RUN=false`. After the regression and full suite pass, inspect the validated diff and authorize publication in the dashboard. The API equivalent is `POST /api/incidents/{id}/authorize` with JSON body `{"authorized":true}` and the orchestrator token in the `X-Orchestrator-Token` header. The orchestrator creates `fix/incident-{id}`, writes the validated changes, and opens a PR with the incident and test evidence.
5. Require protected-branch review in GitHub. Once Scalingo preview validation succeeds, inspect the preview and approve or decline the PR through GitHub. An authorized operator can merge once branch protection allows it. Leave the PR open during a live presentation if you want to retain the validation preview. [GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)

### Troubleshooting

- **401 or 403.** Check token expiry, repository selection, organization approval and its Contents and Pull requests permissions.
- **Dry run or publication still gated.** Check the explicit write setting and the incident-specific authorization. Keep dry run for local demonstrations.
- **Base revision moved.** Run the incident against the intended staging revision again or restore a dedicated rehearsal base branch. Review the reported base commit before approving.
