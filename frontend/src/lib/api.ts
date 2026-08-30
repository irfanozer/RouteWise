import { normalizeComparison, normalizeNetwork, normalizeScenarios } from "./normalize";
import type { CompareRequest, ComparisonRun, Network, Scenario } from "../types";

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/$/, "") ?? "";
const API_ROOT = `${configuredBase}/api/v1`;

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError("The routing service is not reachable. Start the local API, then try again.");
  }

  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : typeof payload === "string" && payload.trim()
          ? payload
          : `Request failed with status ${response.status}.`;
    throw new ApiError(detail, response.status);
  }

  return payload;
}

export const routeWiseApi = {
  async getNetwork(): Promise<Network> {
    return normalizeNetwork(await request("/network"));
  },

  async getScenarios(): Promise<Scenario[]> {
    return normalizeScenarios(await request("/scenarios"));
  },

  async compareRoutes(input: CompareRequest): Promise<ComparisonRun> {
    return normalizeComparison(
      await request("/routes/compare", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    );
  },

  async getRun(runId: string): Promise<ComparisonRun> {
    return normalizeComparison(await request(`/runs/${encodeURIComponent(runId)}`));
  },

  async replayRun(runId: string): Promise<ComparisonRun> {
    const replay = normalizeComparison(
      await request(`/runs/${encodeURIComponent(runId)}/replay`, {
        method: "POST",
      }),
    );
    if (replay.baseline || replay.disrupted) return replay;
    return this.getRun(replay.runId || runId);
  },
};

export const apiRoot = API_ROOT;
