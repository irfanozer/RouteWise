import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EvidencePanel } from "./components/EvidencePanel";
import { NetworkOverviewMap } from "./components/NetworkOverviewMap";
import { RouteCard } from "./components/RouteCard";
import { ScenarioPicker } from "./components/ScenarioPicker";
import { routeWiseApi } from "./lib/api";
import { impactHeadline, objectiveLabels, scenarioAction, stationName } from "./lib/format";
import type {
  AsyncStatus,
  ComparisonRun,
  DemoControls,
  Network,
  Objective,
  Scenario,
} from "./types";

const initialControls: DemoControls = {
  originId: "northgate",
  destinationId: "airport",
  objective: "fastest",
  scenarioId: "central-closure",
};

const objectives: Array<{ value: Objective; label: string; detail: string }> = [
  { value: "fastest", label: "Fastest", detail: "Choose the route with the least total travel time." },
  { value: "fewest_transfers", label: "Fewest transfers", detail: "Reduce how often the traveler changes train lines." },
  { value: "accessible", label: "No stairs", detail: "Only use stations and connections with working elevators or ramps." },
];

interface SubmittedRunContext {
  controls: DemoControls;
  scenario: Scenario;
  originName: string;
  destinationName: string;
}

function snapshotScenario(scenario: Scenario): Scenario {
  return {
    ...scenario,
    closedStationIds: [...scenario.closedStationIds],
    inaccessibleStationIds: [...scenario.inaccessibleStationIds],
    lineDelays: scenario.lineDelays.map((delay) => ({ ...delay })),
    suggestedTrip: { ...scenario.suggestedTrip },
  };
}

function messageFromError(error: unknown): string {
  return error instanceof Error ? error.message : "Something unexpected happened. Please try again.";
}

function preferredId(availableIds: string[], preferred: string, fallbackIndex: number): string {
  if (availableIds.includes(preferred)) return preferred;
  return availableIds[Math.min(fallbackIndex, Math.max(availableIds.length - 1, 0))] ?? "";
}

function LoadingComparison() {
  return (
    <section className="comparison-section" aria-label="Calculating route comparison" aria-busy="true">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Before and after</span>
          <h2>Calculating both routes…</h2>
        </div>
        <span className="loading-chip"><i /> Routing engine working</span>
      </div>
      <div className="comparison-grid">
        {["Baseline route", "Replacement route"].map((label) => (
          <article className="route-card route-card--skeleton" key={label}>
            <span className="sr-only">Loading {label}</span>
            <div className="skeleton skeleton--label" />
            <div className="skeleton skeleton--title" />
            <div className="skeleton skeleton--metrics" />
            <div className="skeleton skeleton--map" />
          </article>
        ))}
      </div>
    </section>
  );
}

function App() {
  const [network, setNetwork] = useState<Network | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [controls, setControls] = useState<DemoControls>(initialControls);
  const [bootstrapStatus, setBootstrapStatus] = useState<AsyncStatus>("loading");
  const [bootstrapError, setBootstrapError] = useState("");
  const [runStatus, setRunStatus] = useState<AsyncStatus>("idle");
  const [runError, setRunError] = useState("");
  const [run, setRun] = useState<ComparisonRun | null>(null);
  const [submittedRun, setSubmittedRun] = useState<SubmittedRunContext | null>(null);
  const [lastAttempt, setLastAttempt] = useState<SubmittedRunContext | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [replayMessage, setReplayMessage] = useState("");
  const resultsRef = useRef<HTMLDivElement>(null);
  const shouldScrollToResultsRef = useRef(false);

  const runComparison = useCallback(async (request: DemoControls, previousAttempt?: SubmittedRunContext) => {
    if (!network) return;
    const scenario = scenarios.find((item) => item.id === request.scenarioId);
    if (!scenario) return;
    shouldScrollToResultsRef.current = true;
    const submission = previousAttempt ?? {
      controls: { ...request },
      scenario: snapshotScenario(scenario),
      originName: stationName(request.originId, network.stations),
      destinationName: stationName(request.destinationId, network.stations),
    };
    setLastAttempt(submission);
    setRunStatus("loading");
    setRunError("");
    setReplayMessage("");
    try {
      const nextRun = await routeWiseApi.compareRoutes({
        origin_id: request.originId,
        destination_id: request.destinationId,
        objective: request.objective,
        scenario_id: request.scenarioId || undefined,
      });
      setRun(nextRun);
      setSubmittedRun(submission);
      setRunStatus(nextRun.baseline ? "success" : "empty");
      setIsDirty(false);
    } catch (error) {
      setRunStatus("error");
      setRunError(messageFromError(error));
    }
  }, [network, scenarios]);

  const initialise = useCallback(async () => {
    setBootstrapStatus("loading");
    setBootstrapError("");
    let loadedNetwork: Network;
    let loadedScenarios: Scenario[];
    try {
      [loadedNetwork, loadedScenarios] = await Promise.all([
        routeWiseApi.getNetwork(),
        routeWiseApi.getScenarios(),
      ]);
    } catch (error) {
      setBootstrapStatus("error");
      setBootstrapError(messageFromError(error));
      return;
    }

    setNetwork(loadedNetwork);
    setScenarios(loadedScenarios);
    if (loadedNetwork.stations.length < 2 || loadedScenarios.length === 0) {
      setBootstrapStatus("empty");
      return;
    }

    const stationIds = loadedNetwork.stations.map((station) => station.id);
    const scenarioIds = loadedScenarios.map((scenario) => scenario.id);
    const defaults: DemoControls = {
      originId: preferredId(stationIds, "northgate", 0),
      destinationId: preferredId(stationIds, "airport", stationIds.length - 1),
      objective: "fastest",
      scenarioId: preferredId(scenarioIds, "central-closure", 0),
    };
    if (defaults.originId === defaults.destinationId) {
      defaults.destinationId = stationIds.find((id) => id !== defaults.originId) ?? "";
    }
    setControls(defaults);
    setRun(null);
    setSubmittedRun(null);
    setLastAttempt(null);
    setRunStatus("idle");
    setIsDirty(false);
    setBootstrapStatus("success");
  }, []);

  useEffect(() => {
    void initialise();
  }, [initialise]);

  useEffect(() => {
    if (runStatus === "idle" || !shouldScrollToResultsRef.current) return;
    shouldScrollToResultsRef.current = false;
    const prefersReducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    resultsRef.current?.scrollIntoView({
      behavior: prefersReducedMotion ? "auto" : "smooth",
      block: "start",
    });
  }, [runStatus]);

  const selectedScenario = useMemo(
    () => scenarios.find((scenario) => scenario.id === controls.scenarioId) ?? scenarios[0] ?? null,
    [controls.scenarioId, scenarios],
  );

  const updateControls = <Key extends keyof DemoControls>(key: Key, value: DemoControls[Key]) => {
    setControls((current) => {
      const next = { ...current, [key]: value };
      if (key === "originId" && value === current.destinationId && network) {
        next.destinationId = network.stations.find((station) => station.id !== value)?.id ?? "";
      }
      return next;
    });
    setIsDirty(true);
    setReplayMessage("");
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void runComparison(controls);
  };

  const handleScenarioSelect = (scenario: Scenario) => {
    setControls({
      scenarioId: scenario.id,
      originId: scenario.suggestedTrip.originId,
      destinationId: scenario.suggestedTrip.destinationId,
      objective: scenario.suggestedTrip.objective,
    });
    setIsDirty(true);
    setReplayMessage("");
  };

  const handleReplay = async () => {
    if (!run?.runId) return;
    setReplaying(true);
    setReplayMessage("");
    try {
      const replayedRun = await routeWiseApi.replayRun(run.runId);
      setRun(replayedRun);
      setRunStatus(replayedRun.baseline ? "success" : "empty");
      setReplayMessage(`Replay complete. Loaded recorded run ${replayedRun.runId || run.runId}.`);
    } catch (error) {
      setReplayMessage(`Replay failed: ${messageFromError(error)}`);
    } finally {
      setReplaying(false);
    }
  };

  const action = selectedScenario && network ? scenarioAction(selectedScenario, network.stations) : "Central Station closes";
  const submittedAction = submittedRun && network
    ? scenarioAction(submittedRun.scenario, network.stations)
    : "";
  const primaryLabel = "Compare normal route with replacement";

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="RouteWise home">
          <svg className="brand__mark" viewBox="0 0 40 40" aria-hidden="true">
            <path d="M7 30C12 30 11 11 19 11s6 18 14 18" />
            <circle cx="7" cy="30" r="3" />
            <circle cx="19" cy="11" r="3" />
            <circle cx="33" cy="29" r="3" />
          </svg>
          <span>RouteWise</span>
        </a>
        <div className="header-meta">
          <span className="header-meta__badge">Interactive engineering demo</span>
          <span className={`service-status service-status--${bootstrapStatus}`}>
            <i aria-hidden="true" />
            {bootstrapStatus === "success" ? "API connected" : bootstrapStatus === "error" ? "API offline" : "Connecting"}
          </span>
        </div>
      </header>

      <main id="top">
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero__copy">
            <span className="eyebrow">Clear before and after route demo</span>
            <h1 id="hero-title">See how one service problem changes a trip.</h1>
            <p>
              Choose where you are going, choose what matters most, and choose what goes wrong. RouteWise shows the
              normal route first, then calculates the best available replacement.
            </p>
            <div className="hero__definition">
              <span>What is a disruption?</span>
              <strong>A real service problem that changes normal travel.</strong>
              <p>In this demo, a station can close, a line can slow down, or station elevators can stop working.</p>
            </div>
            <a className="button button--hero" href="#demo">Choose a test case <span aria-hidden="true">↓</span></a>
          </div>
        </section>

        <section className="plain-language" aria-label="Plain-language definitions">
          <article>
            <span className="plain-language__number">01</span>
            <div><strong>Disruption means service problem</strong><p>A closed station, a delayed line, or elevators that are not working.</p></div>
          </article>
          <article>
            <span className="plain-language__number">02</span>
            <div>
              <strong>No stairs means elevators or ramps all the way</strong>
              <p>This option avoids stairs. It can help wheelchair users, travelers with strollers or luggage, and anyone with limited mobility.</p>
            </div>
          </article>
        </section>

        {bootstrapStatus === "loading" && (
          <section id="demo" className="demo-surface demo-surface--state">
            <div className="map-loading" role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" />
              <div><strong>Loading the Metrovale map</strong><p>Fetching stations, lines, and test cases.</p></div>
            </div>
          </section>
        )}

        {bootstrapStatus === "error" && (
          <section id="demo" className="demo-surface demo-surface--state">
            <div className="bootstrap-state bootstrap-state--error" role="alert">
              <span className="state-icon" aria-hidden="true">!</span>
              <div><strong>We could not reach the routing service</strong><p>{bootstrapError}</p></div>
              <button className="button button--secondary" type="button" onClick={() => void initialise()}>Try again</button>
            </div>
          </section>
        )}

        {bootstrapStatus === "empty" && (
          <section id="demo" className="demo-surface demo-surface--state">
            <div className="bootstrap-state bootstrap-state--empty" role="status">
              <span className="state-icon" aria-hidden="true">○</span>
              <div><strong>The demo network is empty</strong><p>Add at least two stations and one service problem, then refresh.</p></div>
              <button className="button button--secondary" type="button" onClick={() => void initialise()}>Refresh network</button>
            </div>
          </section>
        )}

        {bootstrapStatus === "success" && network && selectedScenario && (
          <section id="demo" className="demo-surface" aria-labelledby="demo-title">
            <div className="demo-surface__heading">
              <div>
                <span className="eyebrow">Eight prepared test cases</span>
                <h2 id="demo-title">Choose a service problem and watch the map update.</h2>
              </div>
              <p>Click any test case. The map beside it marks the problem and loads a trip where the best route changes.</p>
            </div>

            <form className="route-form" onSubmit={handleSubmit}>
              <fieldset className="demo-step demo-step--scenarios">
                <legend><span>1</span><strong>Choose what goes wrong</strong><small>RouteWise calls this a disruption.</small></legend>
                <div className="scenario-workbench">
                  <div className="scenario-workbench__choices">
                    <ScenarioPicker
                      scenarios={scenarios}
                      stations={network.stations}
                      selectedId={controls.scenarioId}
                      disabled={runStatus === "loading"}
                      onSelect={handleScenarioSelect}
                    />
                  </div>
                  <div className="scenario-workbench__map">
                    <NetworkOverviewMap
                      network={network}
                      originId={controls.originId}
                      destinationId={controls.destinationId}
                      scenario={selectedScenario}
                    />
                  </div>
                  <div className={`selected-scenario selected-scenario--${selectedScenario.kind}`}>
                    <div><span>What happened</span><strong>{selectedScenario.summary}</strong></div>
                    <div><span>What it means for this trip</span><strong>{selectedScenario.riderImpact}</strong></div>
                    <div className="selected-scenario__outcome"><span>Prepared outcome</span><strong>This test changes the best route.</strong></div>
                  </div>
                </div>
              </fieldset>

              <div className="demo-step">
                <div className="demo-step__heading"><span>2</span><div><strong>Check the journey</strong><small>Choose the start and destination.</small></div></div>
                <div className="route-form__row route-form__row--journey">
                  <label className="field">
                    <span>Start</span>
                    <select
                      value={controls.originId}
                      disabled={runStatus === "loading"}
                      onChange={(event) => updateControls("originId", event.target.value)}
                    >
                      {network.stations.map((station) => <option value={station.id} key={station.id}>{station.name}</option>)}
                    </select>
                  </label>
                  <span className="journey-arrow" aria-hidden="true">→</span>
                  <label className="field">
                    <span>Destination</span>
                    <select
                      value={controls.destinationId}
                      disabled={runStatus === "loading"}
                      onChange={(event) => updateControls("destinationId", event.target.value)}
                    >
                      {network.stations.filter((station) => station.id !== controls.originId).map((station) => (
                        <option value={station.id} key={station.id}>{station.name}</option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>

              <fieldset className="demo-step objective-fieldset" disabled={runStatus === "loading"}>
                <legend><span>3</span><strong>Choose the route priority</strong><small>RouteWise ranks valid routes using this rule.</small></legend>
                <div className="objective-options">
                  {objectives.map((objective) => (
                    <label key={objective.value} className={controls.objective === objective.value ? "is-selected" : undefined}>
                      <input
                        type="radio"
                        name="objective"
                        value={objective.value}
                        checked={controls.objective === objective.value}
                        onChange={() => updateControls("objective", objective.value)}
                      />
                      <span className="objective-options__check" aria-hidden="true" />
                      <span><strong>{objective.label}</strong><small>{objective.detail}</small></span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div className="run-comparison">
                <div>
                  <span className="eyebrow">What the button does</span>
                  <p>RouteWise calculates the normal trip, applies the selected service problem, and calculates the best available replacement.</p>
                </div>
                <button className="button button--primary" type="submit" disabled={runStatus === "loading"}>
                  <span>{runStatus === "loading" ? "Calculating both routes…" : primaryLabel}</span>
                  <span aria-hidden="true">→</span>
                </button>
              </div>
              {isDirty && submittedRun && (
                <p className="dirty-notice" role="status">Inputs changed. The result below is from the previous run until you recalculate.</p>
              )}
            </form>
          </section>
        )}

        {bootstrapStatus === "success" && (
          <section className="request-path" aria-labelledby="request-path-title">
            <div className="request-path__intro">
              <span className="eyebrow">After you press compare</span>
              <h2 id="request-path-title">Normal route, service problem, replacement route</h2>
            </div>
            <ol>
              <li><span>01</span><div><strong>Calculate normal route</strong><small>Find the best trip before anything goes wrong.</small></div></li>
              <li><span>02</span><div><strong>Apply service problem</strong><small>Close a station, slow a line, or remove elevator access.</small></div></li>
              <li><span>03</span><div><strong>Calculate replacement</strong><small>Use the same trip and priority for a fair comparison.</small></div></li>
            </ol>
          </section>
        )}

        {bootstrapStatus === "success" && network && selectedScenario && (
          <div ref={resultsRef} className="results" aria-live="polite">
            {runStatus === "idle" && (
              <section className="result-state result-state--ready" role="status">
                <span className="state-icon" aria-hidden="true">→</span>
                <div>
                  <strong>Ready to test: {action}</strong>
                  <p>No comparison has been run yet. Use the compare button above to calculate the normal and replacement routes.</p>
                </div>
              </section>
            )}

            {runStatus === "loading" && <LoadingComparison />}

            {runStatus === "error" && (
              <section className="result-state result-state--error" role="alert">
                <span className="state-icon" aria-hidden="true">!</span>
                <div><strong>The route could not be recalculated</strong><p>{runError}</p></div>
                <button
                  type="button"
                  className="button button--secondary"
                  onClick={() => void runComparison(lastAttempt?.controls ?? controls, lastAttempt ?? undefined)}
                >
                  Try this route again
                </button>
              </section>
            )}

            {runStatus === "empty" && (
              <section className="result-state" role="status">
                <span className="state-icon" aria-hidden="true">○</span>
                <div><strong>No baseline route was returned</strong><p>Choose another origin and destination, then recalculate.</p></div>
              </section>
            )}

            {runStatus === "success" && run && submittedRun && (
              <>
                <section className="story-strip" aria-label="Route change summary">
                  <article>
                    <span>Before</span>
                    <strong>{run.baseline ? `${run.baseline.totalMinutes} min via ${run.baseline.stationNames.slice(1, -1).join(", ") || "the direct path"}` : "No baseline"}</strong>
                    <p>{submittedRun.originName} to {submittedRun.destinationName} on the normal network.</p>
                  </article>
                  <span className="story-strip__arrow" aria-hidden="true">→</span>
                  <article className="story-strip__action">
                    <span>Action</span>
                    <strong>{submittedAction}</strong>
                    <p>The engine keeps the original route for a fair comparison.</p>
                  </article>
                  <span className="story-strip__arrow" aria-hidden="true">→</span>
                  <article className="story-strip__result">
                    <span>Result</span>
                    <strong>{impactHeadline(run.impact)}</strong>
                    <p>{run.disrupted ? `A ${objectiveLabels[submittedRun.controls.objective].toLowerCase()} route remains available.` : "No route satisfies every selected constraint."}</p>
                  </article>
                </section>

                <section className="comparison-section" aria-labelledby="comparison-title">
                  <div className="section-heading">
                    <div>
                      <span className="eyebrow">Before and after</span>
                      <h2 id="comparison-title">See exactly what changed</h2>
                    </div>
                    <span className={`impact-badge impact-badge--${run.impact.status}`}>{impactHeadline(run.impact)}</span>
                  </div>
                  <div className="comparison-grid">
                    <RouteCard
                      label="Baseline"
                      title="Original best route"
                      note="Calculated before the disruption is applied."
                      route={run.baseline}
                      network={network}
                      scenario={submittedRun.scenario}
                      variant="baseline"
                    />
                    <RouteCard
                      label="After service problem"
                      title="Replacement route"
                      note={`Optimized for ${objectiveLabels[submittedRun.controls.objective].toLowerCase()} after the network changes.`}
                      route={run.disrupted}
                      network={network}
                      scenario={submittedRun.scenario}
                      variant="replacement"
                    />
                  </div>
                </section>

                <section className="explanation" aria-labelledby="explanation-title">
                  <div className="explanation__icon" aria-hidden="true">i</div>
                  <div className="explanation__body">
                    <span className="eyebrow">Plain-language decision</span>
                    <h2 id="explanation-title">Why this route won</h2>
                    <p className="explanation__summary">{run.explanation.summary}</p>
                    {run.explanation.details.length > 0 && (
                      <ul>{run.explanation.details.map((detail) => <li key={detail}>{detail}</li>)}</ul>
                    )}
                    <p className="explanation__boundary">
                      The routing algorithm makes the decision. The explanation summarizes the recorded result and never chooses the path.
                    </p>
                  </div>
                </section>

                <EvidencePanel
                  run={run}
                  replaying={replaying}
                  replayMessage={replayMessage}
                  onReplay={() => void handleReplay()}
                />
              </>
            )}
          </div>
        )}
      </main>

      <footer>
        <div><strong>RouteWise</strong><span>Disruption-aware, explainable routing</span></div>
        <p>Built as a deterministic engineering demo on a fictional transit network.</p>
      </footer>
    </div>
  );
}

export default App;
