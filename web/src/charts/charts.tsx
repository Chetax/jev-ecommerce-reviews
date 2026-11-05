import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DecisionRow, Metrics, Sentiment } from "../lib/api";
import { humanize, pct } from "../lib/format";
import { SENT_VAR } from "../components/decision";
import { AXIS, ChartCard, DataTable, GRID, Legend, SERIES, TooltipBox } from "./common";


type TipProps = { active?: boolean; payload?: readonly any[]; label?: any };

const SENTS: Sentiment[] = ["negative", "neutral", "positive"];
const BAR = 18;
const CURSOR = { fill: "var(--surface-2)" };

function rowsByTopic(rows: DecisionRow[]) {
  const by = new Map<string, { topic: string; total: number; negative: number; neutral: number; positive: number; defect: number; refund: number }>();
  for (const r of rows) {
    if (!r.topic) continue;
    const t = by.get(r.topic) ?? { topic: r.topic, total: 0, negative: 0, neutral: 0, positive: 0, defect: 0, refund: 0 };
    t.total++;
    if (r.sentiment) t[r.sentiment]++;
    if (r.defect) t.defect++;
    if (r.refund_request) t.refund++;
    by.set(r.topic, t);
  }
  return [...by.values()].sort((a, b) => b.total - a.total);
}

const topicTick = (v: string) => humanize(v);

/* ---------- Topic × sentiment (stacked) ---------- */
export function TopicSentimentChart({ rows }: { rows: DecisionRow[] }) {
  const data = rowsByTopic(rows);
  const height = Math.max(160, data.length * 34 + 30);
  return (
    <ChartCard
      title="Topics by sentiment"
      subtitle="What customers write about, and how they feel about it"
      legend={<Legend items={SENTS.map((s) => ({ label: humanize(s), color: SENT_VAR[s], shape: "square" }))} />}
      chart={
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 0, bottom: 0 }} barSize={BAR}>
            <CartesianGrid {...GRID} horizontal={false} />
            <XAxis type="number" {...AXIS} allowDecimals={false} />
            <YAxis type="category" dataKey="topic" {...AXIS} axisLine={false} width={124} tickFormatter={topicTick} />
            <Tooltip
              cursor={CURSOR}
              content={({ active, payload }: TipProps) =>
                active && payload?.length ? (
                  <TooltipBox
                    title={`${humanize(payload[0].payload.topic)} · ${payload[0].payload.total} reviews`}
                    rows={SENTS.map((s) => ({
                      label: humanize(s),
                      color: SENT_VAR[s],
                      value: `${payload[0].payload[s]} (${pct(payload[0].payload[s] / payload[0].payload.total)})`,
                    }))}
                  />
                ) : null
              }
            />
            {SENTS.map((s, i) => (
              <Bar
                key={s}
                dataKey={s}
                stackId="s"
                fill={SENT_VAR[s]}
                stroke="var(--surface)"
                strokeWidth={2}
                radius={i === SENTS.length - 1 ? [0, 4, 4, 0] : 0}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      }
      table={
        <DataTable
          rows={data}
          columns={[
            { key: "t", label: "Topic", render: (r) => humanize(r.topic) },
            { key: "n", label: "Reviews", align: "right", render: (r) => r.total },
            ...SENTS.map((s) => ({ key: s, label: humanize(s), align: "right" as const, render: (r: (typeof data)[0]) => r[s] })),
          ]}
        />
      }
    />
  );
}

/* ---------- Defect & refund rate by topic (grouped) ---------- */
export function FlagRateChart({ rows }: { rows: DecisionRow[] }) {
  const data = rowsByTopic(rows).map((t) => ({ ...t, defectRate: t.defect / t.total, refundRate: t.refund / t.total }));
  const height = Math.max(160, data.length * 44 + 30);
  return (
    <ChartCard
      title="Defect & refund rate by topic"
      subtitle="Share of each topic's reviews that report a defect or ask for money back"
      legend={
        <Legend
          items={[
            { label: "Defect rate", color: SERIES[0], shape: "square" },
            { label: "Refund / return rate", color: SERIES[1], shape: "square" },
          ]}
        />
      }
      chart={
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }} barSize={12} barGap={2}>
            <CartesianGrid {...GRID} horizontal={false} />
            <XAxis type="number" {...AXIS} domain={[0, 1]} tickFormatter={(v) => pct(v)} />
            <YAxis type="category" dataKey="topic" {...AXIS} axisLine={false} width={124} tickFormatter={topicTick} />
            <Tooltip
              cursor={CURSOR}
              content={({ active, payload }: TipProps) =>
                active && payload?.length ? (
                  <TooltipBox
                    title={humanize(payload[0].payload.topic)}
                    rows={[
                      { label: "Defect", color: SERIES[0], value: `${pct(payload[0].payload.defectRate)} · ${payload[0].payload.defect}` },
                      { label: "Refund / return", color: SERIES[1], value: `${pct(payload[0].payload.refundRate)} · ${payload[0].payload.refund}` },
                    ]}
                  />
                ) : null
              }
            />
            <Bar dataKey="defectRate" fill={SERIES[0]} radius={[0, 4, 4, 0]} isAnimationActive={false} />
            <Bar dataKey="refundRate" fill={SERIES[1]} radius={[0, 4, 4, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      }
      table={
        <DataTable
          rows={data}
          columns={[
            { key: "t", label: "Topic", render: (r) => humanize(r.topic) },
            { key: "n", label: "Reviews", align: "right", render: (r) => r.total },
            { key: "d", label: "Defects", align: "right", render: (r) => `${r.defect} (${pct(r.defectRate)})` },
            { key: "f", label: "Refunds", align: "right", render: (r) => `${r.refund} (${pct(r.refundRate)})` },
          ]}
        />
      }
    />
  );
}

/* ---------- Confidence histogram with threshold ---------- */
export function ConfidenceHistogram({ rows, threshold }: { rows: DecisionRow[]; threshold: number }) {
  const bins = Array.from({ length: 10 }, (_, i) => ({ lo: i / 10, hi: (i + 1) / 10, count: 0 }));
  for (const r of rows) {
    if (r.min_confidence == null) continue;
    bins[Math.min(9, Math.floor(r.min_confidence * 10))].count++;
  }
  const data = bins.map((b) => ({ ...b, label: `${Math.round(b.lo * 100)}–${Math.round(b.hi * 100)}%`, mid: (b.lo + b.hi) / 2 }));
  const below = (b: { hi: number }) => b.hi <= threshold + 1e-9;
  const scored = rows.filter((r) => r.min_confidence != null);
  const auto = scored.filter((r) => (r.min_confidence ?? 0) >= threshold).length;
  return (
    <ChartCard
      title="Confidence distribution"
      subtitle={
        <>
          Lowest field confidence per review. At {pct(threshold)}, <span className="text-ink font-medium">{pct(scored.length ? auto / scored.length : 0)}</span> are
          auto-accepted.
        </>
      }
      legend={
        <Legend
          items={[
            { label: "Needs human review", color: "var(--warning)", shape: "square" },
            { label: "Auto-accepted", color: "var(--accent)", shape: "square" },
          ]}
        />
      }
      chart={
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data} margin={{ left: -16, right: 8 }} barCategoryGap={4}>
            <CartesianGrid {...GRID} vertical={false} />
            <XAxis dataKey="label" {...AXIS} interval={1} />
            <YAxis {...AXIS} axisLine={false} allowDecimals={false} />
            <Tooltip
              cursor={CURSOR}
              content={({ active, payload }: TipProps) =>
                active && payload?.length ? (
                  <TooltipBox
                    title={`Confidence ${payload[0].payload.label}`}
                    rows={[{ label: below(payload[0].payload) ? "Needs review" : "Auto-accepted", value: `${payload[0].payload.count} reviews` }]}
                  />
                ) : null
              }
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false}>
              {data.map((b) => (
                <Cell key={b.lo} fill={below(b) ? "var(--warning)" : "var(--accent)"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      }
      table={
        <DataTable
          rows={data}
          columns={[
            { key: "b", label: "Confidence", render: (r) => r.label },
            { key: "c", label: "Reviews", align: "right", render: (r) => r.count },
            { key: "s", label: "Outcome", render: (r) => (below(r) ? "Needs review" : "Auto-accepted") },
          ]}
        />
      }
    />
  );
}

/* ---------- Benchmark: reliability diagram ---------- */
export function ReliabilityChart({ models }: { models: { name: string; metrics: Metrics }[] }) {
  const lines = models.map((m, i) => ({
    name: m.name,
    color: SERIES[i % SERIES.length],
    data: m.metrics.overall_reliability
      .filter((b) => b.count > 0)
      .map((b) => ({ x: b.avg_confidence!, y: b.accuracy!, n: b.count, model: m.name })),
  }));
  return (
    <ChartCard
      title="Calibration"
      subtitle="Stated confidence vs. actual accuracy. On the diagonal = 90% confident means right 90% of the time."
      legend={
        <Legend items={[...lines.map((l) => ({ label: l.name, color: l.color, shape: "line" as const })), { label: "Perfect calibration", color: "var(--ink-3)", shape: "line" }]} />
      }
      chart={
        <ResponsiveContainer width="100%" height={300}>
          <LineChart margin={{ left: -8, right: 16, top: 8, bottom: 12 }}>
            <CartesianGrid {...GRID} />
            <XAxis type="number" dataKey="x" domain={[0, 1]} ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]} tickFormatter={(v) => pct(v)} {...AXIS}
              label={{ value: "Confidence", position: "insideBottom", offset: -8, fill: "var(--ink-3)", fontSize: 12 }} height={40} />
            <YAxis type="number" domain={[0, 1]} ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]} tickFormatter={(v) => pct(v)} {...AXIS} axisLine={false} />
            <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="var(--ink-3)" strokeDasharray="4 4" ifOverflow="hidden" />
            <Tooltip
              cursor={{ stroke: "var(--axis)" }}
              content={({ active, payload }: TipProps) =>
                active && payload?.length ? (
                  <TooltipBox
                    rows={payload.map((p: any) => ({
                      label: p.payload.model,
                      color: p.stroke,
                      value: `${pct(p.payload.x)} conf → ${pct(p.payload.y)} right · n=${p.payload.n}`,
                    }))}
                  />
                ) : null
              }
            />
            {lines.map((l) => (
              <Line key={l.name} data={l.data} dataKey="y" name={l.name} stroke={l.color} strokeWidth={2} type="linear"
                dot={{ r: 4, fill: l.color, stroke: "var(--surface)", strokeWidth: 2 }} activeDot={{ r: 6, stroke: "var(--surface)", strokeWidth: 2 }}
                isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      }
      table={
        <DataTable
          rows={lines.flatMap((l) => l.data)}
          columns={[
            { key: "m", label: "Model", render: (r) => r.model },
            { key: "c", label: "Avg confidence", align: "right", render: (r) => pct(r.x, 1) },
            { key: "a", label: "Accuracy", align: "right", render: (r) => pct(r.y, 1) },
            { key: "n", label: "Decisions", align: "right", render: (r) => r.n },
          ]}
        />
      }
    />
  );
}

/* ---------- Benchmark: coverage vs accuracy ---------- */
export function CoverageChart({ models }: { models: { name: string; metrics: Metrics }[] }) {
  const lines = models.map((m, i) => ({
    name: m.name,
    color: SERIES[i % SERIES.length],
    data: m.metrics.selective
      .filter((s) => s.all_fields_accuracy != null)
      .map((s) => ({ x: s.coverage, y: s.all_fields_accuracy!, t: s.threshold, model: m.name }))
      .sort((a, b) => a.x - b.x),
  }));
  return (
    <ChartCard
      title="Automation vs. accuracy"
      subtitle="Each point is a confidence threshold: how many reviews you can auto-accept, and how often all 4 fields are right."
      legend={<Legend items={lines.map((l) => ({ label: l.name, color: l.color, shape: "line" as const }))} />}
      chart={
        <ResponsiveContainer width="100%" height={300}>
          <LineChart margin={{ left: -8, right: 16, top: 8, bottom: 12 }}>
            <CartesianGrid {...GRID} />
            <XAxis type="number" dataKey="x" domain={[0, 1]} ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]} tickFormatter={(v) => pct(v)} {...AXIS}
              label={{ value: "Auto-accepted (coverage)", position: "insideBottom", offset: -8, fill: "var(--ink-3)", fontSize: 12 }} height={40} />
            <YAxis type="number" domain={[0, 1]} ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]} tickFormatter={(v) => pct(v)} {...AXIS} axisLine={false} />
            <Tooltip
              cursor={{ stroke: "var(--axis)" }}
              content={({ active, payload }: TipProps) =>
                active && payload?.length ? (
                  <TooltipBox
                    rows={payload.map((p: any) => ({
                      label: `${p.payload.model} @ ${pct(p.payload.t)}`,
                      color: p.stroke,
                      value: `${pct(p.payload.x)} auto · ${pct(p.payload.y)} right`,
                    }))}
                  />
                ) : null
              }
            />
            {lines.map((l) => (
              <Line key={l.name} data={l.data} dataKey="y" name={l.name} stroke={l.color} strokeWidth={2}
                dot={{ r: 4, fill: l.color, stroke: "var(--surface)", strokeWidth: 2 }} activeDot={{ r: 6, stroke: "var(--surface)", strokeWidth: 2 }}
                isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      }
      table={
        <DataTable
          rows={lines.flatMap((l) => l.data)}
          columns={[
            { key: "m", label: "Model", render: (r) => r.model },
            { key: "t", label: "Threshold", align: "right", render: (r) => pct(r.t) },
            { key: "c", label: "Auto-accepted", align: "right", render: (r) => pct(r.x, 1) },
            { key: "a", label: "All-fields accuracy", align: "right", render: (r) => pct(r.y, 1) },
          ]}
        />
      }
    />
  );
}
