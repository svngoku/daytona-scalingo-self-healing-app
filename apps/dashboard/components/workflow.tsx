"use client";

import {
  Background, Handle, Panel, Position, ReactFlow, ReactFlowProvider, useReactFlow,
  type Edge, type Node, type NodeProps, type OnNodesChange,
} from "@xyflow/react";
import {
  Activity, Box, Check, CircleAlert, Code2, FlaskConical, GitPullRequest,
  Maximize, Minus, Plus, ScanSearch, ShieldCheck, Terminal,
  type LucideIcon,
} from "lucide-react";
import type { Incident, RunState } from "@shared/incident";
import { useCallback, useEffect, useState } from "react";
import { label, runEvents } from "@/lib/incident";
import { Button } from "./ui";

const stages = [
  { key: "detect", title: "Detect incident", detail: "Staging", states: ["INCIDENT_DETECTED", "LOGS_COLLECTED"], icon: Activity, tone: "danger", description: "Trigger the staging fault and capture the observable application symptoms." },
  { key: "diagnose", title: "Diagnose", detail: "Orchestrator", states: ["DIAGNOSING"], icon: ScanSearch, tone: "neutral", description: "Examine logs and health checks to identify the likely root cause." },
  { key: "sandbox", title: "Create sandbox", detail: "Sandbox", states: ["SANDBOX_CREATING"], icon: Box, tone: "active", description: "Create an isolated environment for inspecting the source and running commands." },
  { key: "reproduce", title: "Reproduce", detail: "Sandbox", states: ["REPRODUCING"], icon: Terminal, tone: "active", description: "Reproduce the original failure in the isolated sandbox." },
  { key: "fix", title: "Generate fix", detail: "Sandbox", states: ["GENERATING_FIX"], icon: Code2, tone: "active", description: "Prepare a scoped source change and capture its diff." },
  { key: "test", title: "Run tests", detail: "Sandbox", states: ["RUNNING_TESTS"], icon: FlaskConical, tone: "active", description: "Run the regression checks and preserve their output as evidence." },
  { key: "preview", title: "Deploy preview", detail: "GitHub · Scalingo", states: ["PR_CREATING", "REVIEW_APP_DEPLOYING"], icon: GitPullRequest, tone: "purple", description: "Prepare the pull request and validate a Scalingo review app when configured." },
  { key: "approval", title: "Review recovery", detail: "Human approval", states: ["AWAITING_APPROVAL", "COMPLETED"], icon: ShieldCheck, tone: "neutral", description: "Review the evidence and the recovery outcome before any production action." },
] satisfies { key: string; title: string; detail: string; states: RunState[]; icon: LucideIcon; tone: string; description: string }[];

type Stage = typeof stages[number];
type StepStatus = "queued" | "active" | "done" | "failed";
type StageNode = Node<{
  stage: Stage; status: StepStatus; target?: Position; source?: Position;
  select: () => void; highlighted: boolean;
}, "stage">;

function StageCard({ data }: NodeProps<StageNode>) {
  const { stage, status, target, source, select, highlighted } = data;
  const Icon = stage.icon;
  return (
    <div className={`flow-node flow-node-${status} ${highlighted ? "flow-node-selected" : ""}`}>
      {target && <Handle type="target" position={target} />}
      <button className="flow-node-button nodrag nopan" type="button" onClick={select} aria-pressed={highlighted} aria-label={`${stage.title}, ${status}`}>
        <span className={`node-icon node-icon-${stage.tone}`}><Icon size={16} /></span>
        <span className="min-w-0 text-left"><strong>{stage.title}</strong><small>{stage.detail}</small></span>
        {status === "active" && <span className="node-state node-state-active" />}
        {status === "done" && <Check className="node-state node-state-done" size={13} />}
        {status === "failed" && <CircleAlert className="node-state node-state-failed" size={13} />}
      </button>
      {source && <Handle type="source" position={source} />}
    </div>
  );
}

const nodeTypes = { stage: StageCard };

function stageIndex(state: RunState) {
  return stages.findIndex((stage) => stage.states.some((supported) => supported === state));
}

function GraphControls() {
  const { fitView, zoomIn, zoomOut } = useReactFlow();
  return (
    <Panel position="bottom-right" className="flow-controls">
      <Button size="icon" variant="ghost" aria-label="Zoom out" onClick={() => void zoomOut()}><Minus size={15} /></Button>
      <Button size="icon" variant="ghost" aria-label="Zoom in" onClick={() => void zoomIn()}><Plus size={15} /></Button>
      <Button size="icon" variant="ghost" aria-label="Fit workflow to view" onClick={() => void fitView({ padding: 0.11 })}><Maximize size={14} /></Button>
    </Panel>
  );
}

export function Workflow({
  incident, selected, onSelect, stagingLabel, sandboxLabel,
}: { incident: Incident | null; selected: string | null; onSelect: (id: string | null) => void; stagingLabel: string; sandboxLabel: string }) {
  const [compact, setCompact] = useState(false);
  const [measurements, setMeasurements] = useState<Partial<Record<string, { width: number; height: number }>>>({});
  const onNodesChange = useCallback<OnNodesChange<StageNode>>((changes) => {
    setMeasurements((previous) => {
      let next = previous;
      for (const change of changes) {
        if (change.type !== "dimensions" || !change.dimensions) continue;
        const measured = next[change.id];
        const { width, height } = change.dimensions;
        if (measured?.width === width && measured.height === height) continue;
        if (next === previous) next = { ...previous };
        next[change.id] = { width, height };
      }
      return next;
    });
  }, []);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 680px)");
    const resize = () => setCompact(media.matches);
    resize();
    media.addEventListener("change", resize);
    return () => media.removeEventListener("change", resize);
  }, []);

  const events = runEvents(incident);
  const lastStage = events.findLast((event) => stageIndex(event.state) !== -1);
  const activeIndex = lastStage ? stageIndex(lastStage.state) : incident ? stageIndex(incident.state) : -1;
  const stagesReached = new Set(events.map((event) => stageIndex(event.state)));
  const stage = stages.find(({ key }) => key === selected);
  const selectedEvent = stage && events.findLast((event) => stage.states.some((state) => state === event.state));
  const columns = compact ? 2 : 4;
  const nodes: StageNode[] = stages.map((item, index) => {
    const row = Math.floor(index / columns);
    const col = index % columns;
    const forward = row % 2 === 0;
    const x = (forward ? col : columns - 1 - col) * 169;
    const y = row * (compact ? 84 : 115);
    const source = index === stages.length - 1 ? undefined : col === columns - 1
      ? Position.Bottom : forward ? Position.Right : Position.Left;
    const target = index === 0 ? undefined : col === 0
      ? Position.Top : forward ? Position.Left : Position.Right;
    const detail = item.detail === "Sandbox" ? sandboxLabel : item.detail === "Staging" ? stagingLabel : item.detail;
    let status: StepStatus = "queued";
    if (activeIndex === index) {
      if (incident?.state === "FAILED") status = "failed";
      else if (incident?.state === "COMPLETED") status = "done";
      else if (incident?.state !== "CANCELLED" && incident?.artifacts.publication_status !== "dry_run") status = "active";
    } else if (stagesReached.has(index) && index < activeIndex) {
      status = "done";
    }
    return {
      id: item.key, type: "stage",
      position: { x, y },
      measured: measurements[item.key],
      data: { stage: { ...item, detail }, target, source, status, highlighted: item.key === selected, select: () => onSelect(item.key === selected ? null : item.key) },
      draggable: false, connectable: false, selectable: false, focusable: false,
      style: { pointerEvents: "auto" },
    };
  });
  const edges: Edge[] = stages.slice(0, -1).map((item, index) => ({
    id: `${item.key}-${stages[index + 1].key}`, source: item.key, target: stages[index + 1].key,
    type: "smoothstep",
    style: { stroke: nodes[index].data.status === "done" ? "var(--flow-edge-complete)" : "var(--flow-edge)", strokeWidth: 1.2 },
  }));
  return (
    <>
      <div className="flow-canvas" aria-label="Interactive incident recovery workflow">
        <ReactFlowProvider key={columns}>
          <ReactFlow
            nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange}
            fitView fitViewOptions={{ padding: 0.11, maxZoom: 1.1 }} minZoom={0.25}
            nodesDraggable={false} nodesConnectable={false} edgesReconnectable={false}
            zoomOnScroll={false} attributionPosition="bottom-left"
            ariaLabelConfig={{ "node.a11yDescription.default": "Recovery stage" }}
          >
            <Background gap={16} size={1} color="var(--flow-grid)" />
            <GraphControls />
          </ReactFlow>
        </ReactFlowProvider>
      </div>
      <div className="flow-footer">
        {stage ? (
          <div className="min-w-0"><strong>{stage.title}</strong><span>{selectedEvent ? `${label(selectedEvent.state)} · ${selectedEvent.summary}` : stage.description}</span></div>
        ) : (
          <div className="flow-legend" aria-label="Workflow legend">
            <span><i className="legend-dot legend-daytona" />{sandboxLabel}</span>
            <span><i className="legend-dot legend-scalingo" />Scalingo</span>
            <span><i className="legend-dot" />Orchestration &amp; review</span>
          </div>
        )}
      </div>
    </>
  );
}
