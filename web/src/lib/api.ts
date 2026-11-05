export type Field = "topic" | "sentiment" | "defect" | "refund_request";
export const FIELDS: Field[] = ["topic", "sentiment", "defect", "refund_request"];
export type Sentiment = "negative" | "neutral" | "positive";

export interface ModelOption {
  spec: string;
  label: string;
  provider: string;
  disabled?: boolean;
}

export interface AppConfig {
  bedrock_model: string;
  aws_region: string;
  effort: string;
  jev_enabled: boolean;
  tracing_url: string | null;
  sheets_enabled: boolean;
  threshold: number;
  models: ModelOption[];
  topics: string[];
  topic_descriptions: Record<string, string>;
  sentiments: Sentiment[];
}

export type RunStatus = "queued" | "running" | "done" | "failed";

export interface Run {
  id: string;
  created_at: string;
  name: string;
  source: "sample" | "csv" | "sheet";
  model: string;
  threshold: number;
  status: RunStatus;
  total: number;
  done: number;
  failed: number;
  error: string | null;
  cost_usd: number;
  reviewed: number;
  pending_review: number;
}

export interface DecisionRow {
  run_id: string;
  review_id: string;
  position: number;
  text: string;
  topic: string | null;
  sentiment: Sentiment | null;
  defect: boolean | null;
  refund_request: boolean | null;
  confidence: Partial<Record<Field, number>>;
  min_confidence: number | null;
  model: string | null;
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  error: string | null;
  reviewed: boolean;
  corrected: boolean;
  original: Record<Field, string | boolean> | null;
  needs_review: boolean;
}

export interface ReliabilityBin {
  lo: number;
  hi: number;
  count: number;
  avg_confidence: number | null;
  accuracy: number | null;
}

export interface FieldMetrics {
  accuracy: number;
  macro_f1: number;
  ece: number;
  brier: number;
  mean_confidence: number;
  reliability: ReliabilityBin[];
}

export interface Metrics {
  n: number;
  all_fields_accuracy: number;
  per_field: Record<Field, FieldMetrics>;
  overall_ece: number;
  overall_brier: number;
  overall_reliability: ReliabilityBin[];
  selective: { threshold: number; coverage: number; all_fields_accuracy: number | null }[];
  latency_ms: { p50: number; p95: number; mean: number };
  cost: { total_usd: number; per_1k_reviews_usd: number; input_tokens: number; output_tokens: number };
}

export interface BenchmarkReport {
  generated_at: string;
  n_reviews: number;
  threshold: number;
  models: Record<string, { model: string; errors: { review_id: string; error: string }[]; metrics: Metrics }>;
}

export interface Benchmark {
  id: string;
  created_at: string;
  status: RunStatus;
  models: string[];
  progress: Record<string, { done: number; total: number }> | null;
  report: BenchmarkReport | null;
  error: string | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Is `jev-reviews serve` running?");
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail)) msg = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  config: () => req<AppConfig>("/api/config"),
  runs: () => req<Run[]>("/api/runs"),
  run: (id: string) => req<Run>(`/api/runs/${id}`),
  createRun: (body: { source: Run["source"]; model: string; name?: string; csv_text?: string; threshold?: number }) =>
    req<Run>("/api/runs", { method: "POST", body: JSON.stringify(body) }),
  deleteRun: (id: string) => req<void>(`/api/runs/${id}`, { method: "DELETE" }),
  decisions: (id: string) => req<DecisionRow[]>(`/api/runs/${id}/decisions`),
  patchDecision: (
    runId: string,
    reviewId: string,
    body: Partial<Pick<DecisionRow, "topic" | "sentiment" | "defect" | "refund_request" | "reviewed">>,
  ) =>
    req<DecisionRow>(`/api/runs/${runId}/decisions/${encodeURIComponent(reviewId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  pushSheet: (id: string) => req<{ ok: boolean; tab: string }>(`/api/runs/${id}/sheet`, { method: "POST" }),
  exportUrl: (id: string) => `/api/runs/${id}/export.csv`,
  benchmarks: () => req<Benchmark[]>("/api/benchmarks"),
  benchmark: (id: string) => req<Benchmark>(`/api/benchmarks/${id}`),
  createBenchmark: (body: { models: string[]; csv_text?: string }) =>
    req<Benchmark>("/api/benchmarks", { method: "POST", body: JSON.stringify(body) }),
};
