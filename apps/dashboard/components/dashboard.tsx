"use client";

import { Field, FieldDescription, FieldLabel } from "@ui-sdk/react/field";
import { Input } from "@ui-sdk/react/input";
import { Select, SelectContent, SelectItem, SelectLabel, SelectTrigger, SelectValue } from "@ui-sdk/react/select";
import {
  Activity, ArrowRight, Box, ChevronDown, ChevronRight, CircleAlert, Cloud,
  GitBranch, Github, LayoutDashboard, Network, Radio, RefreshCw, Server,
  Settings2, ShieldCheck, Terminal, Workflow as WorkflowIcon, Zap, type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { Incident, ProviderStatus, SystemStatus } from "@shared/incident";
import { eventTime, label, recordedSandboxProvider, safeUrl, stateTone, terminalStates } from "@/lib/incident";
import { publicationSettled, useDashboard, type DashboardData } from "@/lib/use-dashboard";
import { ThemeToggle } from "./app-theme";
import { Approval, CancelDialog, Deployment, Empty, Evidence, External, PanelHeader, Sandbox, TerminalOutput } from "./evidence";
import { Badge, Button, cn } from "./ui";
import { Workflow } from "./workflow";

const views = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "incidents", label: "Incidents", icon: Activity },
  { id: "sandboxes", label: "Sandboxes", icon: Box },
  { id: "deployments", label: "Deployments", icon: Cloud },
  { id: "settings", label: "Settings", icon: Settings2 },
] as const;

type View = typeof views[number]["id"];

function useView() {
  const [view, setView] = useState<View>("overview");
  useEffect(() => {
    function readHash() {
      const hash = window.location.hash.slice(1);
      setView(views.find(({ id }) => id === hash)?.id ?? "overview");
    }
    readHash();
    window.addEventListener("hashchange", readHash);
    return () => window.removeEventListener("hashchange", readHash);
  }, []);
  return view;
}

const providerList = [
  { id: "daytona", title: "Daytona", icon: Box, tone: "active" },
  { id: "scalingo", title: "Scalingo", icon: Cloud, tone: "purple" },
  { id: "github", title: "GitHub", icon: Github, tone: "muted" },
  { id: "openrouter", title: "OpenRouter", icon: Zap, tone: "muted" },
] as const;

function providerHealth(provider?: ProviderStatus) {
  if (!provider) return "muted";
  const status = provider.status.toLowerCase();
  if (["connected", "configured", "ready", "healthy", "available", "active", "local"].includes(status)) return "success";
  if (["error", "failed", "unreachable", "unhealthy"].includes(status)) return "danger";
  if (["simulated", "disabled", "missing", "not_configured", "dry_run"].includes(status)) return "warning";
  return "muted";
}

function providerName(id: typeof providerList[number]["id"], title: string, status: SystemStatus | null) {
  if (status?.providers[id]?.status !== "local") return title;
  return id === "daytona" ? "Local Docker" : id === "scalingo" ? "Local app" : title;
}

function ProviderPill({ icon: Icon, title, status }: { icon: LucideIcon; title: string; status?: ProviderStatus }) {
  return (
    <span className="provider-pill" title={status?.detail || "Provider status unavailable"}>
      <Icon size={14} aria-hidden="true" />{title}
      <span className={`provider-dot provider-dot-${providerHealth(status)}`} />
      <span className="sr-only">{status ? label(status.status) : "Status unavailable"}</span>
    </span>
  );
}

function Shell({ view, status, children }: { view: View; status: SystemStatus | null; children: React.ReactNode }) {
  const active = views.find(({ id }) => id === view) ?? views[0];
  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="sidebar">
        <a href="#overview" className="brand" aria-label="Self-Healing App overview">
          <span className="brand-mark"><Activity size={21} strokeWidth={2.3} /></span>
          <span><strong>Self-Healing App</strong><small>Daytona × Scalingo</small></span>
        </a>
        <nav className="primary-nav" aria-label="Workspace">
          <span className="nav-label">Workspace</span>
          {views.map(({ id, label, icon: Icon }) => (
            <a key={id} className={cn("nav-link", id === view && "nav-link-current")} href={`#${id}`} aria-current={id === view ? "page" : undefined}>
              <Icon size={17} /><span>{label}</span>{id === view && <ChevronRight className="nav-arrow" size={14} />}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="environment-icon"><Radio size={16} /></div>
          <div><strong>{status ? `${label(status.mode)} mode` : "Orchestrator"}</strong><small>{status ? `${status.agent_mode === "fixture" ? "Simulated" : "OpenRouter"} agent` : "Connection pending"}</small></div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><ChevronRight size={13} /><strong>{active.label}</strong></div>
          <div className="providers">
            {providerList.map(({ id, title, icon }) => <ProviderPill key={id} icon={icon} title={providerName(id, title, status)} status={status?.providers[id]} />)}
          </div>
          <ThemeToggle />
        </header>
        <main className="main" id="main-content">{children}</main>
      </div>
    </div>
  );
}

function Staging({ status, loading }: { status: SystemStatus | null; loading: boolean }) {
  const staging = status?.staging;
  const url = safeUrl(staging?.url);
  const tone = staging?.healthy === true ? "success" : staging?.healthy === false ? "danger" : "muted";
  return (
    <section className="panel staging" aria-label="Staging status">
      <div className="staging-main">
        <span className="staging-icon"><Server size={22} /></span>
        <div className="min-w-0"><h2>Staging service</h2><p>{url ? new URL(url).host : "Awaiting a staging endpoint"}</p></div>
      </div>
      <div className="staging-facts">
        <span className="staging-meta"><Cloud size={15} />{providerName("scalingo", "Scalingo", status)}</span>
        {staging?.status_code != null && <code>HTTP {staging.status_code}</code>}
        <Badge tone={tone} dot>{staging?.healthy === true ? "Healthy" : staging?.healthy === false ? "Unhealthy" : loading ? "Checking" : "Unavailable"}</Badge>
        {url && <External href={url} className="inline-link staging-link">Open staging</External>}
      </div>
    </section>
  );
}

function ActivityTimeline({ dashboard }: { dashboard: DashboardData }) {
  const events = dashboard.incident?.events ?? [];
  return (
    <section className="panel activity-panel">
      <PanelHeader icon={Activity} title="Activity"><Badge tone={dashboard.live ? "success" : "muted"} dot>{dashboard.live ? "Live" : dashboard.incident && !publicationSettled(dashboard.incident) && !terminalStates.has(dashboard.incident.state) ? "Connecting" : "Idle"}</Badge></PanelHeader>
      {events.length ? (
        <ol className="timeline" aria-label="Incident activity" tabIndex={0}>
          {[...events].reverse().map((event) => (
            <li key={event.id}>
              <span className={`event-dot event-${event.tool_status}`} aria-hidden="true" />
              <div className="event-entry">
                <div className="event-title"><strong>{label(event.state)}</strong><time dateTime={event.timestamp}>{eventTime(event.timestamp)}</time></div>
                <p>{event.summary}</p>
                {event.error && <p className="event-error">{event.error}</p>}
              </div>
            </li>
          ))}
        </ol>
      ) : <Empty icon={Radio} title="Waiting for activity">Trigger an incident to see the recovery timeline.</Empty>}
    </section>
  );
}

function GuidedDemo({ localStaging, sandboxProvider }: { localStaging: boolean; sandboxProvider: string | null }) {
  return (
    <section className="panel guide">
      <div className="guide-title"><span className="guide-icon"><Network size={19} /></span><div><h2>Guided demo</h2><p>Trigger the staging fault, then follow the evidence through recovery.</p></div></div>
      <div className="guide-steps">
        <div><Cloud size={17} className="guide-scalingo" /><span><strong>{localStaging ? "Local staging" : "Scalingo hosts"}</strong><small>{localStaging ? "The local pricing service provides the staging fault." : "Staging serves the app and review apps validate eligible pull requests."}</small></span></div>
        <ArrowRight size={14} className="guide-arrow" />
        <div><Box size={17} className="guide-daytona" /><span><strong>{sandboxProvider ? `${sandboxProvider} isolates` : "Sandbox isolation"}</strong><small>Each sandbox reproduces the fault, prepares the patch, and runs the checks.</small></span></div>
        <ArrowRight size={14} className="guide-arrow" />
        <div><ShieldCheck size={17} className="guide-review" /><span><strong>You review</strong><small>Inspect the diff, test output, and preview before moving forward.</small></span></div>
      </div>
    </section>
  );
}

function RunPicker({ dashboard }: { dashboard: DashboardData }) {
  if (dashboard.incidents.length < 2) return null;
  const options = dashboard.incidents.map((item) => ({ value: item.id, label: `${item.id} · ${label(item.state)}` }));
  return (
    <div className="run-picker">
      <Select<string>
        items={options}
        value={dashboard.incident?.id ?? null}
        onValueChange={(id) => { if (id) dashboard.select(id); }}
      >
        <SelectLabel>Incident</SelectLabel>
        <SelectTrigger className="run-picker-trigger">
          <SelectValue className="truncate" placeholder="Select an incident" />
          <ChevronDown size={14} aria-hidden="true" />
        </SelectTrigger>
        <SelectContent className="run-options" align="start" sideOffset={5} alignItemWithTrigger={false}>
          {options.map(({ value, label }) => <SelectItem className="run-option" key={value} value={value}>{label}</SelectItem>)}
        </SelectContent>
      </Select>
    </div>
  );
}

function Overview({ dashboard }: { dashboard: DashboardData }) {
  const [stage, setStage] = useState<string | null>(null);
  const { status, incident } = dashboard;
  const localStaging = status?.providers.scalingo?.status === "local";
  const configuredSandbox = status?.providers.daytona
    ? providerName("daytona", "Daytona", status)
    : null;
  const graphSandbox = incident ? recordedSandboxProvider(incident) : configuredSandbox;
  return (
    <>
      <Staging status={dashboard.status} loading={dashboard.loading} />
      <div className="overview-grid">
        <section className="panel">
          <PanelHeader icon={WorkflowIcon} title="Recovery workflow">
            {dashboard.incident ? <Badge tone={dashboard.incident.artifacts.publication_status === "dry_run" ? "success" : stateTone(dashboard.incident.state)} dot>{dashboard.incident.artifacts.publication_status === "dry_run" ? "Dry run ready" : label(dashboard.incident.state)}</Badge> : <Badge dot>Idle</Badge>}
          </PanelHeader>
          <Workflow incident={incident} selected={stage} onSelect={setStage} stagingLabel={localStaging ? "Local staging" : "Staging"} sandboxLabel={graphSandbox ?? "Sandbox"} />
        </section>
        <ActivityTimeline dashboard={dashboard} />
        <Evidence incident={dashboard.incident} />
        <Approval dashboard={dashboard} />
      </div>
      <GuidedDemo localStaging={localStaging} sandboxProvider={configuredSandbox} />
    </>
  );
}

function IncidentHistory({ dashboard }: { dashboard: DashboardData }) {
  const incident = dashboard.incident;
  const retryable = incident && (incident.state === "FAILED" || incident.state === "CANCELLED")
    && incident.attempt < 3 && !incident.artifacts.publication_attempted;
  const cancellable = incident && !terminalStates.has(incident.state) && !publicationSettled(incident);
  return (
    <>
      <section className="panel">
        <PanelHeader icon={Activity} title="Incident history" />
        {dashboard.incidents.length > 0 ? (
          <div className="history">
            {dashboard.incidents.map((item) => (
              <button className={cn("history-item", item.id === incident?.id && "history-item-active")} key={item.id} type="button" aria-pressed={item.id === incident?.id} onClick={() => dashboard.select(item.id)}>
                <span><strong>{item.summary || "Staging incident"}</strong><small>{item.id} · Attempt {item.attempt}</small></span>
                <Badge tone={stateTone(item.state)} dot>{label(item.state)}</Badge><ChevronRight size={16} />
              </button>
            ))}
          </div>
        ) : <Empty icon={Zap} title={dashboard.loading ? "Loading incidents…" : "No incidents yet"}>Trigger a staging incident to start a recovery run.</Empty>}
      </section>
      {incident && (
        <>
          <section className="panel">
            <PanelHeader icon={GitBranch} title="Selected incident">
              {retryable && <Button size="small" disabled={Boolean(dashboard.action)} focusableWhenDisabled={dashboard.action === "retry"} onClick={() => dashboard.mutate("retry")}><RefreshCw size={14} />Retry incident</Button>}
              {cancellable && <CancelDialog dashboard={dashboard} />}
            </PanelHeader>
            <div className="selected-run"><span><small>Incident</small><code>{incident.id}</code></span><span><small>Correlation ID</small><code>{incident.correlation_id}</code></span><span><small>Attempt</small><strong>{incident.attempt}</strong></span></div>
            {incident.error && <p className="incident-error" role="status">{incident.error}</p>}
          </section>
          <div className="overview-grid"><Evidence incident={incident} /><ActivityTimeline dashboard={dashboard} /></div>
          <Approval dashboard={dashboard} />
        </>
      )}
    </>
  );
}

function Settings({ dashboard }: { dashboard: DashboardData }) {
  const [draft, setDraft] = useState<string | null>(null);
  const value = draft ?? dashboard.token;
  return (
    <div className="overview-grid">
      <section className="panel">
        <PanelHeader icon={Server} title="Provider configuration" />
        <div className="settings-providers">
          {providerList.map(({ id, title, icon: Icon, tone }) => {
            const provider = dashboard.status?.providers[id];
            return <div className="settings-provider" key={id}><span className={`node-icon node-icon-${tone}`}><Icon size={18} /></span><span><strong>{providerName(id, title, dashboard.status)}</strong><small>{provider?.detail || "Status unavailable"}</small></span><Badge tone={providerHealth(provider)} dot>{provider ? label(provider.status) : "Unknown"}</Badge></div>;
          })}
        </div>
      </section>
      <section className="panel">
        <PanelHeader icon={Settings2} title="Orchestrator access" />
        <form className="settings-form" onSubmit={(event) => {
          event.preventDefault();
          dashboard.updateToken(value);
          setDraft(null);
        }}>
          <Field className="settings-field">
            <FieldLabel>API token</FieldLabel>
            <FieldDescription>Enter the orchestrator token if your API requires one. It is saved for this browser tab.</FieldDescription>
            <Input type="password" autoComplete="off" value={value} placeholder="Token" onValueChange={setDraft} />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary">Apply token</Button>
            {value && <Button variant="ghost" onClick={() => { dashboard.updateToken(""); setDraft(null); }}>Clear token</Button>}
          </div>
        </form>
        <div className="settings-flags">
          <span>GitHub writes <Badge tone={dashboard.status?.github_write_enabled ? "warning" : "muted"}>{dashboard.status ? dashboard.status.github_write_enabled ? "Enabled" : "Disabled" : "Unknown"}</Badge></span>
          <span>GitHub dry run <Badge>{dashboard.status ? dashboard.status.github_dry_run ? "On" : "Off" : "Unknown"}</Badge></span>
        </div>
      </section>
    </div>
  );
}

const descriptions: Record<View, { title: string; body: string }> = {
  overview: { title: "Incident recovery", body: "Observe, diagnose, and validate a staging recovery from one workspace." },
  incidents: { title: "Incidents", body: "Inspect recovery attempts, event history, and remediation evidence." },
  sandboxes: { title: "Sandboxes", body: "Inspect the isolated environment and commands for a recovery run." },
  deployments: { title: "Deployments", body: "Check staging health and review deployment evidence for the selected incident." },
  settings: { title: "Settings", body: "Manage dashboard access and inspect provider configuration." },
};

export function Dashboard() {
  const view = useView();
  const dashboard = useDashboard();
  const { title, body } = descriptions[view];
  const open = dashboard.incidents.some((item) => !terminalStates.has(item.state) && !publicationSettled(item));
  const canTrigger = Boolean(dashboard.status && !dashboard.loading && !dashboard.error && !dashboard.action && !open);
  return (
    <Shell view={view} status={dashboard.status}>
      <div className="page-heading">
        <div>
          {view === "overview" && <div className="page-kicker"><span />Recovery workspace</div>}
          <h1>{title}</h1><p>{body}</p>
        </div>
        {(view === "overview" || view === "incidents") && (
          <div className="heading-actions">
            <Button variant="primary" disabled={!canTrigger} focusableWhenDisabled={dashboard.action === "trigger"} onClick={() => dashboard.mutate("trigger")}><Zap size={16} />{dashboard.action === "trigger" ? "Triggering…" : "Trigger Incident"}</Button>
          </div>
        )}
        {(view === "sandboxes" || view === "deployments") && <RunPicker dashboard={dashboard} />}
      </div>
      {dashboard.error && (
        <section className="offline" role="status">
          <CircleAlert size={18} /><div><strong>Orchestrator unavailable</strong><p>{dashboard.error}</p></div>
          <Button size="small" onClick={dashboard.refresh}><RefreshCw size={14} />Retry connection</Button>
        </section>
      )}
      {dashboard.actionError && <p className="action-error" role="alert">{dashboard.actionError}</p>}
      {view === "overview" && <><RunPicker dashboard={dashboard} /><Overview dashboard={dashboard} /></>}
      {view === "incidents" && <IncidentHistory dashboard={dashboard} />}
      {view === "sandboxes" && <><Sandbox incident={dashboard.incident} /><section className="panel"><PanelHeader icon={Terminal} title="Sandbox commands" /><TerminalOutput incident={dashboard.incident} /></section></>}
      {view === "deployments" && <><Staging status={dashboard.status} loading={dashboard.loading} /><div className="overview-grid"><Deployment incident={dashboard.incident} status={dashboard.status} /><Approval dashboard={dashboard} /></div></>}
      {view === "settings" && <Settings dashboard={dashboard} />}
    </Shell>
  );
}
