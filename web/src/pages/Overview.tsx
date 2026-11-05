import { ArrowRight, Inbox, Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ConfidenceHistogram, FlagRateChart, TopicSentimentChart } from "../charts/charts";
import { PageHeader } from "../components/Layout";
import { NewRunButton } from "../components/NewRun";
import { Button, Card, Empty, ErrorBanner, Skeleton } from "../components/ui";
import { modelLabel, num, pct, timeAgo, usd } from "../lib/format";
import { useDecisions, useSelectedRun } from "../lib/hooks";

function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-[13px] text-ink-2">
        {label}
        {accent}
      </div>
      <div className="text-[26px] font-semibold tracking-tight mt-1.5 leading-none">{value}</div>
      {sub && <div className="text-xs text-ink-2 mt-2">{sub}</div>}
    </Card>
  );
}

export function OverviewSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-64" />
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-24" />)}
      </div>
      <div className="grid xl:grid-cols-2 gap-4">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>
    </div>
  );
}

export function Overview() {
  const { run, loading } = useSelectedRun();
  const { data: rows, isLoading, error } = useDecisions(run);

  if (loading || (run && isLoading)) return <OverviewSkeleton />;
  if (!run)
    return (
      <Card>
        <Empty
          icon={<Sparkles className="size-5" />}
          title="Classify your first batch of reviews"
          body="Start with the 48 sample reviews, upload a CSV, or pull straight from your Google Sheet. Each review gets a topic, sentiment, and defect/refund flags with a confidence score."
          action={<NewRunButton label="Start a run" />}
        />
      </Card>
    );
  if (error) return <ErrorBanner error={error} />;

  const all = rows ?? [];
  const scored = all.filter((r) => r.topic != null);
  const n = scored.length;
  const negative = scored.filter((r) => r.sentiment === "negative").length;
  const defects = scored.filter((r) => r.defect).length;
  const refunds = scored.filter((r) => r.refund_request).length;
  const pending = scored.filter((r) => r.needs_review && !r.reviewed).length;
  const auto = scored.filter((r) => !r.needs_review).length;
  const cost = scored.reduce((s, r) => s + (r.cost_usd ?? 0), 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title={run.name}
        subtitle={
          <>
            {num(run.total)} reviews · {modelLabel(run.model)} · threshold {pct(run.threshold)} · {timeAgo(run.created_at)}
          </>
        }
        actions={
          pending > 0 && (
            <Link to="/queue">
              <Button variant="primary" icon={<Inbox className="size-4" />}>
                Review {pending} flagged <ArrowRight className="size-4" />
              </Button>
            </Link>
          )
        }
      />

      {run.error && <ErrorBanner error={run.error} />}

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <Stat label="Classified" value={num(n)} sub={run.failed ? `${run.failed} failed` : `of ${num(run.total)}`} />
        <Stat label="Negative" value={pct(n ? negative / n : 0)} sub={`${negative} reviews`} />
        <Stat label="Defects reported" value={num(defects)} sub={pct(n ? defects / n : 0) + " of reviews"} />
        <Stat label="Refund / return asks" value={num(refunds)} sub={pct(n ? refunds / n : 0) + " of reviews"} />
        <Stat label="Auto-accepted" value={pct(n ? auto / n : 0)} sub={`${pending} waiting for review`} />
        <Stat label="Model cost" value={usd(cost)} sub={n ? `${usd((cost / n) * 1000)} per 1k reviews` : undefined} />
      </div>

      {n === 0 ? (
        <Card>
          <Empty icon={<Sparkles className="size-5" />} title="Waiting for the first decisions" body="Charts fill in as reviews are classified." />
        </Card>
      ) : (
        <>
          <div className="grid xl:grid-cols-2 gap-4">
            <TopicSentimentChart rows={scored} />
            <FlagRateChart rows={scored} />
          </div>
          <ConfidenceHistogram rows={scored} threshold={run.threshold} />
        </>
      )}
    </div>
  );
}
