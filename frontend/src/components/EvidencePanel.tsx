import { timingLabel } from "../lib/format";
import type { ComparisonRun } from "../types";

interface EvidencePanelProps {
  run: ComparisonRun;
  replaying: boolean;
  replayMessage: string;
  onReplay: () => void;
}

function constraintLabel(constraints: Record<string, unknown>): string {
  const entries = Object.entries(constraints).filter(([, value]) => value !== null && value !== undefined);
  if (!entries.length) return "None";
  return entries
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${String(value)}`)
    .join(" · ");
}

export function EvidencePanel({ run, replaying, replayMessage, onReplay }: EvidencePanelProps) {
  const { evidence } = run;
  return (
    <details className="evidence-panel">
      <summary>
        <span>
          <span className="evidence-panel__eyebrow">Technical evidence</span>
          <strong>Inspect the decision record</strong>
        </span>
        <span className="evidence-panel__hint">Run ID, algorithm, cache, timing, replay</span>
      </summary>
      <div className="evidence-panel__body">
        <p className="evidence-panel__intro">
          Every comparison records the exact graph and disruption snapshot, making the result explainable and repeatable.
        </p>
        <dl className="evidence-grid">
          <div>
            <dt>Run ID</dt>
            <dd><code>{run.runId || "Not reported"}</code></dd>
          </div>
          <div>
            <dt>Algorithm</dt>
            <dd>{evidence.algorithm ?? "Not reported by API"}</dd>
          </div>
          <div>
            <dt>Network version</dt>
            <dd><code>{evidence.networkVersion}</code></dd>
          </div>
          <div>
            <dt>Disruption version</dt>
            <dd><code>{evidence.disruptionVersion}</code></dd>
          </div>
          <div>
            <dt>Baseline cache</dt>
            <dd>{evidence.cache.baselineHit ? "Hit, safely reused" : "Miss, calculated fresh"}</dd>
          </div>
          <div>
            <dt>Disrupted cache</dt>
            <dd>{evidence.cache.disruptedHit ? "Hit, safely reused" : "Miss, calculated fresh"}</dd>
          </div>
          <div>
            <dt>Cache invalidations</dt>
            <dd>{evidence.cache.invalidatedEntries}</dd>
          </div>
          <div>
            <dt>Routing timing</dt>
            <dd>{timingLabel(evidence.timingMs)}</dd>
          </div>
          <div>
            <dt>Objective</dt>
            <dd>{evidence.objective.replaceAll("_", " ")}</dd>
          </div>
          <div>
            <dt>Scenario</dt>
            <dd><code>{evidence.scenarioId}</code></dd>
          </div>
          <div>
            <dt>Constraints</dt>
            <dd>{constraintLabel(evidence.constraints)}</dd>
          </div>
          <div>
            <dt>Replay source</dt>
            <dd>{evidence.replayedFromRunId ? <code>{evidence.replayedFromRunId}</code> : "Original run"}</dd>
          </div>
        </dl>
        {evidence.decisionFactors.length > 0 && (
          <div className="decision-factors">
            <strong>Recorded decision factors</strong>
            <ul>{evidence.decisionFactors.map((factor) => <li key={factor}>{factor}</li>)}</ul>
          </div>
        )}
        <div className="evidence-panel__replay">
          <div>
            <strong>Historical replay</strong>
            <p>Run the same saved inputs against their recorded snapshot.</p>
          </div>
          <button
            type="button"
            className="button button--secondary"
            disabled={replaying || !evidence.replayable || !run.runId}
            onClick={onReplay}
          >
            {replaying ? "Replaying…" : "Replay this exact run"}
          </button>
        </div>
        <p className="replay-message" role="status" aria-live="polite">{replayMessage}</p>
      </div>
    </details>
  );
}
