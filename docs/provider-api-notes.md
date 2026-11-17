# Provider API contracts

## Daytona and Docker

The hosted adapter uses the stable [Daytona Python SDK 0.231.1](https://pypi.org/project/daytona/0.231.1/). The adapter creates a private, ephemeral sandbox with a wall-clock TTL. It delegates blocking SDK operations to worker threads and uses the SDK's command timeout and delete wait. The sandbox checks out the exact GitHub commit from a public allowlisted repository. The supported hosted path currently requires a public repo. GitHub credentials stay in the orchestrator. [Daytona SDK](https://www.daytona.io/docs/en/python-sdk/sync/daytona/) · [Sandbox network policy](https://www.daytona.io/docs/en/python-sdk/sync/sandbox/#sandboxupdate_network_settings) · [Process API](https://www.daytona.io/docs/en/python-sdk/sync/process/)

Docker's local demo stages the application's Python files and requirements into a private worktree with a fresh Git baseline. The container has CPU, memory, and process limits and no host workspace mount. Both sandbox providers install the baseline dependencies before disconnecting outbound access. The worker exposes three fixed actions for listing Python sources, reproducing the target regression, and running the application tests.

## Scalingo

The adapter exchanges the configured API token at the central authentication API, then uses the bearer token against the application's regional Scalingo v1 endpoint. It requests a signed application logs URL and fetches up to 200 lines through that URL, without forwarding the bearer token. Match results retain neighboring lines so that unkeyed traceback lines remain available. [Scalingo token exchange and regions](https://developers.scalingo.com/) · [Application logs URL](https://developers.scalingo.com/apps) · [Log history protocol](https://developers.scalingo.com/logs)

Review app lookup matches the pull request number in the configured application's SCM integration. Once the review app deployment succeeds, the adapter reads the app's URL from the regional API. Automatic review apps must already be enabled on the linked Scalingo app. [Integration link API](https://developers.scalingo.com/scm_repo_link) · [Deployments API](https://developers.scalingo.com/deployments)

## GitHub

The GitHub integration pins REST API version 2026-03-10. With the GitHub write flag and incident approval in place, a token with repository Contents and Pull requests write permissions can create a tree and child commit, publish a fix branch for the incident, and open a pull request against the configured default branch. The repository must be explicitly allowlisted. Retry after an interrupted publication can reuse the incident branch and pull request if the existing branch has the same parent and tree. Dry runs return the planned branch with empty pull request and commit identifiers. [Git Data API](https://docs.github.com/en/rest/git) · [Pull requests API](https://docs.github.com/en/rest/pulls/pulls)
