"use client";

import {
  AlertDialog, AlertDialogBackdrop, AlertDialogClose, AlertDialogContent,
  AlertDialogDescription, AlertDialogTitle, AlertDialogTrigger,
} from "@ui-sdk/react/alert-dialog";
import { Tabs, TabsList, TabsPanel, TabsTab, TabsTabIcon } from "@ui-sdk/react/tabs";
import {
  ArrowUpRight, Box, ClipboardList, ExternalLink, FileCode2, FlaskConical, GitPullRequest,
  ShieldCheck, Terminal, type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Incident, SystemStatus } from "@shared/incident";
import { array, label, record, recordedSandboxProvider, safeUrl, string } from "@/lib/incident";
import type { DashboardData } from "@/lib/use-dashboard";
import { Badge, buttonVariants } from "./ui";

export function PanelHeader({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return (
    <div className="panel-header">
      <h2><Icon size={17} />{title}</h2>
      {children}
    </div>
  );
}

export function Empty({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return <div className="empty"><span className="empty-icon"><Icon size={18} /></span><strong>{title}</strong>{children && <p>{children}</p>}</div>;
}

export function External({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return <a href={href} target="_blank" rel="noreferrer" className={className}>{children}<ArrowUpRight size={14} aria-hidden="true" /></a>;
}

export function Details({ rows }: { rows: { label: string; content: ReactNode }[] }) {
  return <dl className="details">{rows.map(({ label, content }) => <div key={label}><dt>{label}</dt><dd>{content}</dd></div>)}</dl>;
}

export function TerminalOutput({ incident }: { incident: Incident | null }) {
  const commands = array(incident?.artifacts.commands).map(record);
  if (!commands.length) {
    return <Empty icon={Terminal} title="No sandbox commands yet">Command output appears when the sandbox runs a step.</Empty>;
  }
  return (
    <div className="terminal-scroll" tabIndex={0} aria-label="Sandbox command output">
      {commands.map((command, index) => {
        const stdout = string(command.stdout);
        const stderr = string(command.stderr);
        const exit = command.exit_code;
        return (
          <div className="terminal-command" key={index}>
            <div className="terminal-command-header"><code><span>$</span> {string(command.command) || "Sandbox command"}</code>
              {typeof exit === "number" && <Badge tone={exit === 0 ? "success" : "danger"}>exit {exit}</Badge>}
            </div>
            {stdout && <pre>{stdout}</pre>}
            {stderr && <pre className="terminal-stderr">{stderr}</pre>}
          </div>
        );
      })}
    </div>
  );
}

function Diff({ diff, title = "Patch diff" }: { diff: string; title?: string }) {
  if (!diff) return <Empty icon={FileCode2} title="No patch captured yet">A unified diff appears after the agent proposes a fix.</Empty>;
  return (
    <div className="diff-scroll" tabIndex={0} aria-label={title}>
      <pre>{diff.split("\n").map((line, index) => {
        const tone = line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@") ? "meta"
          : line.startsWith("+") ? "added" : line.startsWith("-") ? "removed" : "";
        return <span className={`diff-line diff-${tone}`} key={index}>{line || " "}</span>;
      })}</pre>
    </div>
  );
}

function Tests({ incident }: { incident: Incident | null }) {
  const passed = incident?.artifacts.tests_passed;
  const verified = passed === true;
  const testSummary = string(record(incident?.artifacts.report).validation_summary);
  const testEvents = (incident?.events ?? []).filter((event) => event.state === "RUNNING_TESTS");
  if (!verified && !testEvents.length) {
    return <Empty icon={FlaskConical} title="No test result yet">Regression and validation results appear here after tests run.</Empty>;
  }
  return (
    <div className="evidence-stack">
      <Badge tone={verified ? "success" : "muted"} dot>{verified ? "Regression passed" : "Pass pending"}</Badge>
      {testSummary && <p className="test-summary">{testSummary}</p>}
      {testEvents.length > 0 && <pre className="report">{testEvents.map((event) => event.summary).join("\n")}</pre>}
    </div>
  );
}

function Report({ incident }: { incident: Incident | null }) {
  const report = incident?.artifacts.report;
  const diagnosis = record(incident?.artifacts.diagnosis);
  if (!report && !Object.keys(diagnosis).length) {
    return <Empty icon={ClipboardList} title="No report yet">The diagnosis and remediation report appear as evidence is captured.</Empty>;
  }
  return (
    <div className="evidence-stack">
      {Object.keys(diagnosis).length > 0 && (
        <Details rows={[
          { label: "Root cause", content: string(diagnosis.root_cause) || "Pending" },
          ...(diagnosis.confidence != null ? [{ label: "Confidence", content: String(diagnosis.confidence) }] : []),
          ...(diagnosis.summary ? [{ label: "Summary", content: string(diagnosis.summary) }] : []),
        ]} />
      )}
      {report != null && <pre className="report">{typeof report === "string" ? report : JSON.stringify(report, null, 2)}</pre>}
    </div>
  );
}

const tabs = [
  { key: "terminal", label: "Terminal", icon: Terminal },
  { key: "diff", label: "Diff", icon: FileCode2 },
  { key: "tests", label: "Tests", icon: FlaskConical },
  { key: "report", label: "Report", icon: ClipboardList },
];

export function Evidence({ incident }: { incident: Incident | null }) {
  return (
    <section className="panel">
      <PanelHeader icon={ClipboardList} title="Run evidence">
        {incident?.artifacts.simulated === true && <Badge tone="warning">Simulated agent</Badge>}
      </PanelHeader>
      <Tabs defaultValue="terminal">
        <TabsList className="evidence-tabs" aria-label="Run evidence">
          {tabs.map(({ key, label, icon: Icon }) => (
            <TabsTab className="evidence-tab" value={key} key={key}><TabsTabIcon><Icon size={15} /></TabsTabIcon>{label}</TabsTab>
          ))}
        </TabsList>
        <TabsPanel value="terminal"><TerminalOutput incident={incident} /></TabsPanel>
        <TabsPanel value="diff"><Diff diff={string(incident?.artifacts.diff)} /></TabsPanel>
        <TabsPanel value="tests"><Tests incident={incident} /></TabsPanel>
        <TabsPanel value="report"><Report incident={incident} /></TabsPanel>
      </Tabs>
    </section>
  );
}

export function CancelDialog({ dashboard }: { dashboard: DashboardData }) {
  return (
    <AlertDialog pendingAnnouncement="Cancelling incident">
      <AlertDialogTrigger className={buttonVariants({ size: "small", variant: "ghost" })} disabled={Boolean(dashboard.action)}>Cancel incident</AlertDialogTrigger>
      <AlertDialogBackdrop className="dialog-overlay" />
      <AlertDialogContent className="dialog-content">
        <AlertDialogTitle>Cancel this incident?</AlertDialogTitle>
        <AlertDialogDescription>The orchestrator will stop the recovery workflow. Existing evidence stays in incident history.</AlertDialogDescription>
        {dashboard.actionError && <p className="action-error" role="alert">{dashboard.actionError}</p>}
        <div className="dialog-actions">
          <AlertDialogClose className={buttonVariants({ variant: "ghost" })}>Keep running</AlertDialogClose>
          <AlertDialogClose
            className={buttonVariants({ variant: "danger" })}
            value="confirm"
            action={async () => {
              if (!(await dashboard.mutate("cancel"))) throw new Error("The incident could not be cancelled.");
            }}
          >{dashboard.action === "cancel" ? "Cancelling…" : "Cancel incident"}</AlertDialogClose>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function AuthorizeDialog({ dashboard }: { dashboard: DashboardData }) {
  const incident = dashboard.incident;
  const target = record(incident?.artifacts.authorization_target);
  const repository = string(target.repository);
  const branch = string(target.branch);
  const base = string(target.base_sha);
  const diff = string(incident?.artifacts.diff);
  const enabled = Boolean(repository && branch && base && diff && incident?.artifacts.tests_passed === true
    && dashboard.status?.github_write_enabled && !dashboard.status.github_dry_run);
  return (
    <AlertDialog pendingAnnouncement="Publishing patch">
      <AlertDialogTrigger className={buttonVariants({ variant: "primary" })} disabled={!enabled || Boolean(dashboard.action)}>
        <GitPullRequest size={16} aria-hidden="true" />Review GitHub publish
      </AlertDialogTrigger>
      <AlertDialogBackdrop className="dialog-overlay" />
      <AlertDialogContent className="dialog-content dialog-wide">
        <AlertDialogTitle>Publish this patch to GitHub?</AlertDialogTitle>
        <AlertDialogDescription>Approving creates a branch and draft pull request for this incident. Merge and production release remain external review steps.</AlertDialogDescription>
        <Details rows={[
          { label: "Repository", content: repository },
          { label: "Branch", content: branch },
          { label: "Base commit", content: base },
          { label: "Tests", content: <Badge tone="success">Passed</Badge> },
        ]} />
        <Diff diff={diff} title="Diff to publish" />
        {dashboard.actionError && <p className="action-error" role="alert">{dashboard.actionError}</p>}
        <div className="dialog-actions">
          <AlertDialogClose className={buttonVariants({ variant: "ghost" })}>Go back</AlertDialogClose>
          <AlertDialogClose
            className={buttonVariants({ variant: "primary" })}
            value="confirm"
            disabled={!enabled}
            action={async () => {
              if (!(await dashboard.mutate("authorize"))) throw new Error("The patch could not be published.");
            }}
          >{dashboard.action === "authorize" ? "Publishing…" : "Authorize branch and draft PR"}</AlertDialogClose>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function Approval({ dashboard }: { dashboard: DashboardData }) {
  const { incident } = dashboard;
  const artifacts = incident?.artifacts;
  const pr = record(artifacts?.pr);
  const pullRequest = safeUrl(pr.url);
  const dryRun = artifacts?.publication_status === "dry_run" || pr.dry_run === true;
  const required = artifacts?.authorization_required === true;
  const readyForReview = incident?.state === "AWAITING_APPROVAL";
  return (
    <section className="panel">
      <PanelHeader icon={ShieldCheck} title="Human approval">
        <Badge tone={required || readyForReview ? "warning" : "muted"}>
          {required ? "Action required" : readyForReview ? "Review required" : dryRun ? "Dry run" : "Manual"}
        </Badge>
      </PanelHeader>
      <div className="approval-body">
        <span className="approval-icon"><ShieldCheck size={24} /></span>
        <strong>{required ? "Approve branch and draft PR" : readyForReview ? "Review the pull request" : dryRun ? "Validated patch ready" : "Production is a manual step"}</strong>
        <p>{required
          ? "Inspect the source change and verified target before authorizing GitHub writes."
          : readyForReview
            ? "Review the evidence and the preview, then take any merge or release action in GitHub and Scalingo."
            : dryRun
              ? "This run prepared a patch in dry-run mode. A live pull request and review app were not created."
              : "Evidence and preview links appear as the recovery run progresses. Review and release happen outside this dashboard."}</p>
        {required && <AuthorizeDialog dashboard={dashboard} />}
        {pullRequest && <External href={pullRequest} className="inline-link"><GitPullRequest size={15} />Open pull request</External>}
      </div>
    </section>
  );
}

export function Sandbox({ incident }: { incident: Incident | null }) {
  const sandbox = record(incident?.artifacts.sandbox);
  const id = string(sandbox.id);
  return (
    <section className="panel">
      <PanelHeader icon={Box} title="Sandbox environment">
        {id && <Badge tone="active" dot>{label(string(sandbox.status) || "Provisioned")}</Badge>}
      </PanelHeader>
      {id ? <Details rows={[
        { label: "Sandbox ID", content: <code>{id}</code> },
        { label: "Provider", content: recordedSandboxProvider(incident) ?? "Not recorded" },
      ]} /> : <Empty icon={Box} title="No sandbox recorded">Select a recovery run with sandbox evidence.</Empty>}
    </section>
  );
}

export function Deployment({ incident, status }: { incident: Incident | null; status: SystemStatus | null }) {
  const artifacts = incident?.artifacts;
  const review = record(artifacts?.review_app);
  const pr = record(artifacts?.pr);
  const stageUrl = safeUrl(status?.staging.url);
  const previewUrl = safeUrl(review.url);
  const prUrl = safeUrl(pr.url);
  const dry = artifacts?.publication_status === "dry_run" || pr.dry_run === true;
  return (
    <section className="panel">
      <PanelHeader icon={ExternalLink} title="Deployment evidence"><Badge tone="purple">Scalingo</Badge></PanelHeader>
      <Details rows={[
        { label: "Staging service", content: stageUrl ? <External href={stageUrl} className="inline-link">{new URL(stageUrl).host}</External> : "URL unavailable" },
        { label: "Health probe", content: status?.staging.healthy === true ? "Healthy" : status?.staging.healthy === false ? "Unhealthy" : "Unavailable" },
        { label: "Pull request", content: prUrl ? <External href={prUrl} className="inline-link">{pr.number ? `PR #${pr.number}` : "Open pull request"}</External> : dry ? "Dry run" : "None recorded" },
        { label: "Preview", content: previewUrl ? <External href={previewUrl} className="inline-link">{new URL(previewUrl).host}</External> : label(string(review.status) || "None recorded") },
        { label: "Preview health", content: artifacts?.preview_validated === true ? "Validated" : dry ? "Skipped in dry run" : incident?.state === "FAILED" && previewUrl ? "Validation failed" : "Pending evidence" },
        { label: "Production health", content: artifacts?.production_verified === true ? "Verified" : "Pending verification" },
      ]} />
    </section>
  );
}
