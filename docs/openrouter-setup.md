# OpenRouter model configuration

The orchestrator uses the OpenAI Python SDK against OpenRouter's Responses endpoint. Models and credentials come from OpenRouter; an `OPENAI_API_KEY` is not used by this integration.

For real model repairs with local Docker isolation, set:

```dotenv
DEMO_MODE=true
AGENT_MODE=openrouter
SANDBOX_PROVIDER=docker
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_MODEL=openai/gpt-5-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
GITHUB_DRY_RUN=true
GITHUB_WRITE_ENABLED=false
```

Restart the orchestrator after changing configuration. Keep the key in its server environment or ignored `.env` file. Dashboard Settings accepts the separate orchestrator access token, never the provider key. The default fixture mode remains available without provider credentials and is explicitly labeled as scripted.

## Model requirements

Choose an OpenRouter model with function tools and structured outputs. The default `openai/gpt-5-mini` completed real repairs in Docker and Daytona during validation. Catalog capabilities vary by endpoint. The client requests required-parameter routing and verifies the resulting response before executing tools. It processes independent calls sequentially within the local budget and requires `finish` in its own response. The request omits the optional `parallel_tool_calls` parameter. [Validation results](validation.md)

Diagnosis uses a strict JSON schema. Repair allows up to 12 tool calls and 12 model rounds per attempt, with up to three attempts. Rejected calls and `finish` count toward the call limit. A retry can report a retained sandbox patch after inspecting it again. The model can inspect scoped Python files, propose edits in the sandbox, and run the supported test commands. The fixture remains a separate provider mode.

Responses use `store=false` and full conversation replay. Tool call IDs and opaque reasoning items are preserved for subsequent requests; opaque reasoning is not displayed in the dashboard. The configured base URL is restricted to OpenRouter's API origin. [Responses API](https://openrouter.ai/docs/api_reference/responses/overview) · [Tool calling](https://openrouter.ai/docs/api_reference/responses/tool-calling) · [Provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)

## Troubleshooting

| Failure | Check |
| --- | --- |
| Missing key | Set `OPENROUTER_API_KEY` in the orchestrator environment and restart. |
| HTTP 401/403 | Check the OpenRouter key, account access, and model restrictions. |
| HTTP 404 | Confirm the model ID and that its available endpoints accept the requested tool and structured-output parameters. |
| HTTP 402/429 | Check account credit, request limits, and provider availability before retrying. |
| Incomplete or malformed response | The agent rejects it before tool execution; inspect the incident's sanitized error and retry with a compatible model if necessary. |

To run the repair in Daytona, choose [local staging and a dry run](../README.md#use-daytona-with-local-staging) or [Scalingo staging and explicit publication](../README.md#run-with-cloud-services).
