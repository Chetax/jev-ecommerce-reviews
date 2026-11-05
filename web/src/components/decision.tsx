import { AlertTriangle, CheckCircle2, Hammer, PencilLine, RotateCcw, Wrench, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { FIELDS, type AppConfig, type DecisionRow, type Field, type Sentiment } from "../lib/api";
import { humanize, pct } from "../lib/format";
import { Badge, Segmented, cx } from "./ui";

export const SENT_VAR: Record<Sentiment, string> = { negative: "var(--neg)", neutral: "var(--neu)", positive: "var(--pos)" };

export function SentimentPill({ value }: { value: Sentiment | null }) {
  if (!value) return <span className="text-ink-3">–</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px] text-ink">
      <span className="size-2 rounded-full" style={{ background: SENT_VAR[value] }} />
      {humanize(value)}
    </span>
  );
}

export function TopicTag({ value }: { value: string | null }) {
  if (!value) return <span className="text-ink-3">–</span>;
  return <Badge>{humanize(value)}</Badge>;
}

export function Flags({ row }: { row: Pick<DecisionRow, "defect" | "refund_request"> }) {
  if (!row.defect && !row.refund_request) return <span className="text-ink-3 text-[13px]">None</span>;
  return (
    <span className="inline-flex gap-1">
      {row.defect && <Badge tone="critical" icon={<Wrench className="size-3" />}>Defect</Badge>}
      {row.refund_request && <Badge tone="warning" icon={<RotateCcw className="size-3" />}>Refund</Badge>}
    </span>
  );
}

/** Confidence as a short meter; fill tone carries severity relative to the threshold. */
export function ConfidenceMeter({ value, threshold, width = 64 }: { value: number | null | undefined; threshold: number; width?: number }) {
  if (value == null) return <span className="text-ink-3">–</span>;
  const low = value < threshold;
  return (
    <span className="inline-flex items-center gap-2" title={`Confidence ${pct(value, 1)} (threshold ${pct(threshold)})`}>
      <span className="relative h-1.5 rounded-full overflow-hidden" style={{ width, background: low ? "var(--warning-soft)" : "var(--accent-soft)" }}>
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${value * 100}%`, background: low ? "var(--warning)" : "var(--accent)" }}
        />
      </span>
      <span className="tabular text-[13px] text-ink-2 w-9 text-right">{pct(value)}</span>
    </span>
  );
}

export function ReviewState({ row }: { row: DecisionRow }) {
  if (row.error) return <Badge tone="critical" icon={<AlertTriangle className="size-3" />}>Error</Badge>;
  if (row.topic == null) return <Badge>Pending</Badge>;
  if (row.corrected) return <Badge tone="accent" icon={<PencilLine className="size-3" />}>Corrected</Badge>;
  if (row.reviewed) return <Badge tone="good" icon={<CheckCircle2 className="size-3" />}>Reviewed</Badge>;
  if (row.needs_review) return <Badge tone="warning" icon={<AlertTriangle className="size-3" />}>Needs review</Badge>;
  return <Badge icon={<Zap className="size-3" />}>Auto-accepted</Badge>;
}

export type Labels = { topic: string; sentiment: Sentiment; defect: boolean; refund_request: boolean };

export const labelsOf = (r: DecisionRow): Labels => ({
  topic: r.topic ?? "other",
  sentiment: r.sentiment ?? "neutral",
  defect: !!r.defect,
  refund_request: !!r.refund_request,
});

function FieldRow({ label, conf, threshold, changed, children }: {
  label: string;
  conf?: number;
  threshold: number;
  changed?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="py-3.5 border-b border-line last:border-0">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-medium text-ink flex items-center gap-2">
          {label}
          {changed && <Badge tone="accent">Edited</Badge>}
        </span>
        <ConfidenceMeter value={conf} threshold={threshold} />
      </div>
      {children}
    </div>
  );
}

/** Editable typed decision. Controlled: parent owns `value`. */
export function DecisionEditor({ row, value, onChange, config, threshold }: {
  row: DecisionRow;
  value: Labels;
  onChange: (v: Labels) => void;
  config: AppConfig;
  threshold: number;
}) {
  const orig = row.original as Labels | null;
  const changed = (f: Field) => orig != null && orig[f] !== value[f];
  const yesNo = (f: "defect" | "refund_request", icon: ReactNode) => (
    <Segmented
      label={humanize(f)}
      value={value[f] ? "yes" : "no"}
      onChange={(v) => onChange({ ...value, [f]: v === "yes" })}
      options={[
        { value: "no", label: "No" },
        { value: "yes", label: <span className="inline-flex items-center gap-1">{icon}Yes</span> },
      ]}
    />
  );
  return (
    <div>
      <FieldRow label="Topic" conf={row.confidence.topic} threshold={threshold} changed={changed("topic")}>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Topic">
          {config.topics.map((t) => {
            const active = value.topic === t;
            return (
              <button
                key={t}
                role="radio"
                aria-checked={active}
                title={config.topic_descriptions[t]}
                onClick={() => onChange({ ...value, topic: t })}
                className={cx(
                  "h-8 px-3 rounded-lg text-[13px] font-medium border transition-colors",
                  active ? "bg-accent text-accent-ink border-transparent" : "bg-surface border-line-strong text-ink-2 hover:text-ink hover:bg-surface-2",
                )}
              >
                {humanize(t)}
              </button>
            );
          })}
        </div>
      </FieldRow>
      <FieldRow label="Sentiment" conf={row.confidence.sentiment} threshold={threshold} changed={changed("sentiment")}>
        <Segmented
          label="Sentiment"
          value={value.sentiment}
          onChange={(v) => onChange({ ...value, sentiment: v })}
          options={config.sentiments.map((s) => ({
            value: s,
            label: (
              <span className="inline-flex items-center gap-1.5">
                <span className="size-2 rounded-full" style={{ background: SENT_VAR[s] }} />
                {humanize(s)}
              </span>
            ),
          }))}
        />
      </FieldRow>
      <FieldRow label="Reports a defect" conf={row.confidence.defect} threshold={threshold} changed={changed("defect")}>
        {yesNo("defect", <Hammer className="size-3.5" />)}
      </FieldRow>
      <FieldRow label="Wants refund / return" conf={row.confidence.refund_request} threshold={threshold} changed={changed("refund_request")}>
        {yesNo("refund_request", <RotateCcw className="size-3.5" />)}
      </FieldRow>
    </div>
  );
}

export const isDirty = (row: DecisionRow, v: Labels) => FIELDS.some((f) => labelsOf(row)[f] !== v[f]);
