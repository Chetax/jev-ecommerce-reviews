import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Info, Trophy } from "lucide-react";
import { useEffect, useState } from "react";
import { CoverageChart, ReliabilityChart } from "../charts/charts";
import { SERIES } from "../charts/common";
import { PageHeader } from "../components/Layout";
import { Badge, Button, Card, CardHeader, Empty, ErrorBanner, Progress, RunStatusBadge, Select, Skeleton, cx } from "../components/ui";
import { api, FIELDS, type Benchmark as B, type Metrics } from "../lib/api";
import { humanize, ms, pct, timeAgo, usd } from "../lib/format";
import { useConfig } from "../lib/hooks";

type Row = { label: string; hint?: string; get: (m: Metrics) => number; fmt: (v: number) => string; better: "high" | "low" };

const ROWS: Row[] = [
  { label: "All 4 fields correct", get: (m) => m.all_fields_accuracy, fmt: (v) => pct(v, 1), better: "high" },
  ...FIELDS.map<Row>((f) => ({ label: `${humanize(f)} accuracy`, get: (m) => m.per_field[f].accuracy, fmt: (v) => pct(v, 1), better: "high" })),
  { label: "Topic macro-F1", get: (m) => m.per_field.topic.macro_f1, fmt: (v) => v.toFixed(3), better: "high" },
  { label: "Calibration error (ECE)", hint: "Gap between stated confidence and accuracy. Lower is better.", get: (m) => m.overall_ece, fmt: (v) => v.toFixed(3), better: "low" },
  { label: "Brier score", hint: "Penalises confident mistakes. Lower is better.", get: (m) => m.overall_brier, fmt: (v) => v.toFixed(3), better: "low" },
  { label: "Latency p50", get: (m) => m.latency_ms.p50, fmt: ms, better: "low" },
  { label: "Latency p95", get: (m) => m.latency_ms.p95, fmt: ms, better: "low" },
  { label: "Cost per 1k reviews", get: (m) => m.cost.per_1k_reviews_usd, fmt: usd, better: "low" },
];

export function Benchmark() {
  const { data: config } = useConfig();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string[]>(["bedrock"]);
  const [viewId, setViewId] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["benchmarks"],
    queryFn: api.benchmarks,
    refetchInterval: (q) => (q.state.data?.some((b) => b.status === "running" || b.status === "queued") ? 1000 : false),
  });
  const create = useMutation({
    mutationFn: () => api.createBenchmark({ models: selected }),
    onSuccess: (b) => {
      setViewId(b.id);
      qc.invalidateQueries({ queryKey: ["benchmarks"] });
    },
  });

  const benches = list.data ?? [];
  const current: B | undefined = benches.find((b) => b.id === viewId) ?? benches[0];
  useEffect(() => {
    if (config?.jev_enabled) setSelected((s) => (s.includes("jev") ? s : [...s, "jev"]));
  }, [config?.jev_enabled]);

  if (!config || list.isLoading) return <Skeleton className="h-[600px]" />;
  const toggle = (spec: string) => setSelected((s) => (s.includes(spec) ? s.filter((x) => x !== spec) : [...s, spec]));
  const running = current && (current.status === "running" || current.status === "queued");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Benchmark"
        subtitle="Accuracy, calibration, speed and cost on the 48 hand-labeled sample reviews"
        actions={
          benches.length > 1 && (
            <Select
              label="Past benchmarks"
              className="w-72"
              value={current?.id ?? ""}
              onChange={setViewId}
              options={benches.map((b) => ({ value: b.id, label: `${b.models.join(" vs ")} · ${timeAgo(b.created_at)}` }))}
            />
          )
        }
      />

      <Card className="p-5">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex-1 min-w-[260px]">
            <div className="text-[13px] font-medium mb-2">Models to compare</div>
            <div className="flex flex-wrap gap-2">
              {config.models.map((m) => {
                const on = selected.includes(m.spec);
                return (
                  <button
                    key={m.spec}
                    disabled={m.disabled}
                    onClick={() => toggle(m.spec)}
                    aria-pressed={on}
                    title={m.disabled ? "Set TYPESAFE_API_KEY to enable Jev" : undefined}
                    className={cx(
                      "h-9 px-3 rounded-lg border text-sm font-medium inline-flex items-center gap-2 transition-colors disabled:opacity-45 disabled:cursor-not-allowed",
                      on ? "border-accent bg-accent-soft text-accent" : "border-line-strong text-ink-2 hover:bg-surface-2",
                    )}
                  >
                    <span className={cx("size-3.5 rounded border grid place-items-center", on ? "bg-accent border-accent" : "border-line-strong")}>
                      {on && <svg viewBox="0 0 12 12" className="size-2.5"><path d="M2.5 6.2l2.2 2.2L9.5 3.6" stroke="white" strokeWidth="1.8" fill="none" strokeLinecap="round" /></svg>}
                    </span>
                    {m.label}
                    <span className="text-xs font-normal text-ink-3">{m.provider}</span>
                  </button>
                );
              })}
            </div>
          </div>
          <Button variant="primary" icon={<FlaskConical className="size-4" />} disabled={!selected.length || !!running} loading={create.isPending} onClick={() => create.mutate()}>
            Run benchmark
          </Button>
        </div>
        {!config.jev_enabled && (
          <p className="flex items-center gap-1.5 text-xs text-ink-2 mt-3">
            <Info className="size-3.5" /> Jev is a paid TypeSafe API and isn't on Bedrock. Add <code>TYPESAFE_API_KEY</code> to include it.
          </p>
        )}
        <div className="mt-3"><ErrorBanner error={create.error} /></div>
      </Card>

      {!current ? (
        <Card>
          <Empty icon={<FlaskConical className="size-5" />} title="No benchmarks yet" body="Pick one or more models and run a benchmark to compare them." />
        </Card>
      ) : running ? (
        <Card className="p-5 space-y-4">
          <div className="flex items-center gap-2"><RunStatusBadge status={current.status} /><span className="text-sm text-ink-2">Running {current.models.join(", ")}</span></div>
          {current.models.map((m) => {
            const p = current.progress?.[m];
            return (
              <div key={m}>
                <div className="flex justify-between text-[13px] mb-1.5"><span>{m}</span><span className="tabular text-ink-2">{p ? `${p.done}/${p.total}` : "waiting"}</span></div>
                <Progress value={p ? p.done / p.total : 0} />
              </div>
            );
          })}
        </Card>
      ) : current.status === "failed" ? (
        <ErrorBanner error={current.error ?? "Benchmark failed"} />
      ) : current.report ? (
        <Results bench={current} />
      ) : null}
    </div>
  );
}

function Results({ bench }: { bench: B }) {
  const report = bench.report!;
  const models = Object.entries(report.models).map(([name, m]) => ({ name, model: m.model, errors: m.errors, metrics: m.metrics }));
  const best = (r: Row) => {
    const vals = models.filter((m) => m.metrics.n > 0).map((m) => r.get(m.metrics));
    if (vals.length < 2) return null;
    const b = r.better === "high" ? Math.max(...vals) : Math.min(...vals);
    return vals.every((v) => r.fmt(v) === r.fmt(b)) ? null : b;
  };
  return (
    <div className="space-y-4">
      {models.some((m) => m.errors.length) && (
        <ErrorBanner error={models.filter((m) => m.errors.length).map((m) => `${m.name}: ${m.errors.length} reviews failed (e.g. ${m.errors[0].error})`).join(" · ")} />
      )}
      <Card>
        <CardHeader title="Scorecard" subtitle={`${report.n_reviews} labeled reviews · ${timeAgo(bench.created_at)}`} />
        <div className="overflow-x-auto px-5 pb-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-[13px] text-ink-2">
                <th className="text-left font-medium py-2.5 pr-3">Metric</th>
                {models.map((m, i) => (
                  <th key={m.name} className="text-right font-medium py-2.5 px-3">
                    <span className="inline-flex items-center gap-1.5 text-ink">
                      <span className="size-2.5 rounded-full" style={{ background: SERIES[i % SERIES.length] }} />
                      {m.name}
                    </span>
                    {m.model.replace("anthropic.", "") !== m.name && (
                      <div className="text-xs font-normal text-ink-3">{m.model.replace("anthropic.", "")}</div>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular">
              {ROWS.map((r) => {
                const b = best(r);
                return (
                  <tr key={r.label} className="border-b border-line last:border-0">
                    <td className="py-2.5 pr-3 text-ink-2" title={r.hint}>{r.label}</td>
                    {models.map((m) => {
                      const v = r.get(m.metrics);
                      const win = b != null && r.fmt(v) === r.fmt(b);
                      return (
                        <td key={m.name} className={cx("py-2.5 px-3 text-right", win ? "text-ink font-semibold" : "text-ink-2")}>
                          <span className="inline-flex items-center gap-1.5">
                            {win && <Badge tone="good" className="h-5 px-1.5" icon={<Trophy className="size-3" />}>Best</Badge>}
                            {m.metrics.n ? r.fmt(v) : "–"}
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="grid xl:grid-cols-2 gap-4">
        <ReliabilityChart models={models} />
        <CoverageChart models={models} />
      </div>
    </div>
  );
}
