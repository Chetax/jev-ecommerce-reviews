import { ArrowLeft, ArrowRight, Check, CheckCircle2, Inbox, PartyPopper } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "../components/Layout";
import { DecisionEditor, isDirty, labelsOf, type Labels } from "../components/decision";
import { NewRunButton } from "../components/NewRun";
import { Button, Card, Empty, ErrorBanner, Progress, Skeleton, useToast } from "../components/ui";
import { pct } from "../lib/format";
import { useConfig, useDecisions, usePatchDecision, useSelectedRun } from "../lib/hooks";

const SENT_KEYS: Record<string, Labels["sentiment"]> = { n: "negative", u: "neutral", p: "positive" };

export function Queue() {
  const { run, loading } = useSelectedRun();
  const { data: config } = useConfig();
  const { data: rows, isLoading } = useDecisions(run);
  const patch = usePatchDecision(run?.id);
  const toast = useToast();

  const queue = useMemo(
    () => (rows ?? []).filter((r) => r.needs_review && !r.reviewed).sort((a, b) => (a.min_confidence ?? 0) - (b.min_confidence ?? 0)),
    [rows],
  );
  const flaggedTotal = useMemo(() => (rows ?? []).filter((r) => r.needs_review).length, [rows]);
  const [idx, setIdx] = useState(0);
  const current = queue.length ? queue[Math.min(idx, queue.length - 1)] : undefined;
  const [value, setValue] = useState<Labels | null>(null);

  useEffect(() => {
    setValue(current ? labelsOf(current) : null);
  }, [current?.review_id]);

  const submit = () => {
    if (!current || !value || patch.isPending) return;
    const corrected = isDirty(current, value);
    patch.mutate(
      { reviewId: current.review_id, body: { ...value, reviewed: true } },
      {
        onSuccess: () => toast({ tone: "good", text: corrected ? `Corrected ${current.review_id}` : `Approved ${current.review_id}` }),
        onError: (e) => toast({ tone: "critical", text: e.message }),
      },
    );
  };
  const skip = (d: 1 | -1) => queue.length && setIdx((i) => (Math.min(i, queue.length - 1) + d + queue.length) % queue.length);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (!current || !value || !config) return;
      const t = e.target as HTMLElement;
      if (t.closest("input,textarea,select") || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "enter" || k === "a") submit();
      else if (k === "arrowright" || k === "s") skip(1);
      else if (k === "arrowleft") skip(-1);
      else if (k === "d") setValue({ ...value, defect: !value.defect });
      else if (k === "r") setValue({ ...value, refund_request: !value.refund_request });
      else if (SENT_KEYS[k]) setValue({ ...value, sentiment: SENT_KEYS[k] });
      else if (/^[1-9]$/.test(k) && config.topics[Number(k) - 1]) setValue({ ...value, topic: config.topics[Number(k) - 1] });
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  if (loading || (run && isLoading) || !config) return <Skeleton className="h-[560px]" />;
  if (!run)
    return (
      <Card>
        <Empty icon={<Inbox className="size-5" />} title="Nothing to review yet" body="Start a run; low-confidence decisions will land here." action={<NewRunButton label="Start a run" />} />
      </Card>
    );

  const doneCount = flaggedTotal - queue.length;
  const header = (
    <PageHeader
      title="Review queue"
      subtitle={`Decisions below ${pct(run.threshold)} confidence, least confident first`}
      actions={
        flaggedTotal > 0 && (
          <div className="w-56">
            <div className="flex justify-between text-[13px] text-ink-2 mb-1.5">
              <span>{doneCount} of {flaggedTotal} done</span>
              <span className="tabular">{pct(doneCount / flaggedTotal)}</span>
            </div>
            <Progress value={doneCount / flaggedTotal} />
          </div>
        )
      }
    />
  );

  if (!current || !value)
    return (
      <div>
        {header}
        <Card>
          <Empty
            icon={flaggedTotal ? <PartyPopper className="size-5" /> : <CheckCircle2 className="size-5" />}
            title={flaggedTotal ? "Queue cleared" : "Nothing needs review"}
            body={flaggedTotal ? `All ${flaggedTotal} flagged decisions have been reviewed.` : "Every decision in this run cleared the confidence threshold."}
            action={<Link to="/reviews"><Button>Browse all reviews</Button></Link>}
          />
        </Card>
      </div>
    );

  const dirty = isDirty(current, value);
  const position = Math.min(idx, queue.length - 1) + 1;

  return (
    <div>
      {header}
      <div className="grid lg:grid-cols-[1fr_380px] gap-4 items-start">
        <Card className="p-6 anim-fade" key={current.review_id}>
          <div className="flex items-center justify-between mb-4">
            <span className="text-[13px] text-ink-2">
              <span className="font-mono text-ink">{current.review_id}</span> · {position} of {queue.length} left
            </span>
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => skip(-1)} icon={<ArrowLeft className="size-4" />} aria-label="Previous" />
              <Button size="sm" variant="ghost" onClick={() => skip(1)} icon={<ArrowRight className="size-4" />} aria-label="Skip" />
            </div>
          </div>
          <p className="text-lg leading-relaxed text-ink">{current.text}</p>
          <div className="mt-6 pt-2 border-t border-line">
            <DecisionEditor row={current} value={value} onChange={setValue} config={config} threshold={run.threshold} />
          </div>
          <ErrorBanner error={patch.error} />
          <div className="flex flex-wrap items-center justify-end gap-2 mt-5">
            {dirty && <Button variant="ghost" onClick={() => setValue(labelsOf(current))}>Reset</Button>}
            <Button variant="secondary" onClick={() => skip(1)}>Skip</Button>
            <Button variant="primary" loading={patch.isPending} onClick={submit} icon={<Check className="size-4" />}>
              {dirty ? "Save correction" : "Approve"}
            </Button>
          </div>
        </Card>

        <Card className="p-5 text-[13px] lg:sticky lg:top-20">
          <h3 className="font-semibold text-sm mb-3">Keyboard</h3>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 items-center text-ink-2">
            <dt><kbd>A</kbd> <kbd>↵</kbd></dt><dd>Approve / save correction</dd>
            <dt><kbd>S</kbd> <kbd>→</kbd></dt><dd>Skip</dd>
            <dt><kbd>←</kbd></dt><dd>Previous</dd>
            <dt><kbd>1</kbd>–<kbd>{config.topics.length}</kbd></dt><dd>Set topic</dd>
            <dt><kbd>N</kbd> <kbd>U</kbd> <kbd>P</kbd></dt><dd>Negative / neutral / positive</dd>
            <dt><kbd>D</kbd></dt><dd>Toggle defect</dd>
            <dt><kbd>R</kbd></dt><dd>Toggle refund</dd>
          </dl>
          <h3 className="font-semibold text-sm mt-5 mb-2">Topics</h3>
          <ol className="space-y-1 text-ink-2">
            {config.topics.map((t, i) => (
              <li key={t} className="flex gap-2"><kbd>{i + 1}</kbd><span className={value.topic === t ? "text-ink font-medium" : ""}>{t.replace(/_/g, " ")}</span></li>
            ))}
          </ol>
        </Card>
      </div>
    </div>
  );
}
