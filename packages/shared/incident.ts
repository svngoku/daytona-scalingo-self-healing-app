export type RunState =
  | "IDLE" | "INCIDENT_DETECTED" | "LOGS_COLLECTED" | "DIAGNOSING"
  | "SANDBOX_CREATING" | "REPRODUCING" | "GENERATING_FIX" | "RUNNING_TESTS"
  | "PR_CREATING" | "REVIEW_APP_DEPLOYING" | "AWAITING_APPROVAL"
  | "COMPLETED" | "FAILED" | "CANCELLED" | "RETRYING";

export interface WorkflowEvent {
  id: number;
  incident_id: string;
  timestamp: string;
  state: RunState;
  summary: string;
  tool_status: "running" | "success" | "error" | "info";
  outputs: Record<string, unknown>;
  error: string | null;
}

export interface Incident {
  id: string;
  state: RunState;
  created_at: string;
  updated_at: string;
  attempt: number;
  summary: string;
  error: string | null;
  correlation_id: string;
  events: WorkflowEvent[];
  artifacts: Record<string, unknown>;
}

export interface ProviderStatus {
  status: string;
  detail: string;
}

export interface SystemStatus {
  mode: "local" | "live";
  agent_mode: "openrouter" | "fixture";
  providers: Record<"daytona" | "scalingo" | "github" | "openrouter", ProviderStatus>;
  staging: { url: string | null; healthy: boolean | null; status_code: number | null };
  github_write_enabled: boolean;
  github_dry_run: boolean;
}
