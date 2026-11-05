import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, ListChecks, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "../components/Layout";
import {
  ConfidenceMeter,
  DecisionEditor,
  Flags,
  ReviewState,
  SentimentPill,
  TopicTag,
  isDirty,
  labelsOf,
  type Labels,
} from "../components/decision";
import { NewRunButton } from "../components/NewRun";
import { Button, Card, Drawer, Empty, ErrorBanner, Select, Skeleton, cx, inputCls, useToast } from "../components/ui";
import { api, type AppConfig, type DecisionRow, type Run } from "../lib/api";
import { humanize, ms, pct, usd } from "../lib/format";
import { useConfig, useDecisions, usePatchDecision, useSelectedRun } from "../lib/hooks";

const PAGE = 25;
type Status = "all" | "needs_review" | "auto" | "reviewed" | "corrected" | "error";
type SortKey = "position" | "min_confidence";

function matchStatus(r: DecisionRow, s: Status) {
  switch (s) {
    case "all": return true;
    case "needs_review": return r.needs_review && !r.reviewed;
    case "auto": return r.topic != null && !r.needs_review && !r.reviewed;
    case "reviewed": return r.reviewed && !r.corrected;
    case "corrected": return r.corrected;
    case "error": return !!r.error;
  }
}

export function Reviews() {
  const { run, loading } = useSelectedRun();
  const { data: config } = useConfig();
  const { data: rows, isLoading, error } = useDecisions(run);
  const [params, setParams] = useSearchParams();

  const q = params.get("q") ?? "";
  const topic = params.get("topic") ?? "all";
  const sentiment = params.get("sentiment") ?? "all";
  const flag = params.get("flag") ?? "all";
  const status = (params.get("status") as Status) ?? "all";
  const sort = (params.get("sort") as SortKey) ?? "position";
  const dir = params.get("dir") === "desc" ? -1 : 1;
  const [page, setPage] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);

  const set = (k: string, v: string, def = "all") => {
    const next = new URLSearchParams(params);
    if (v === def || !v) next.delete(k);
    else next.set(k, v);
    setParams(next, { replace: true });
    setPage(0);
  };

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const out = (rows ?? []).filter(
      (r) =>
        (!needle || r.text.toLowerCase().includes(needle) || r.review_id.toLowerCase().includes(needle)) &&
        (topic === "all" || r.topic === topic) &&
        (sentiment === "all" || r.sentiment === sentiment) &&
        (flag === "all" || (flag === "defect" ? r.defect : flag === "refund" ? r.refund_request : !r.defect && !r.refund_request)) &&
        matchStatus(r, status),
    );
    return out.sort((a, b) => ((a[sort] ?? -1) > (b[sort] ?? -1) ? 1 : (a[sort] ?? -1) < (b[sort] ?? -1) ? -1 : 0) * dir);
  }, [rows, q, topic, sentiment, flag, status, sort, dir]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  useEffect(() => {
    if (page >= pages) setPage(pages - 1);
  }, [page, pages]);
  const visible = filtered.slice(page * PAGE, page * PAGE + PAGE);
  const openRow = rows?.find((r) => r.review_id === openId) ?? null;
  const anyFilter = q || topic !== "all" || sentiment !== "all" || flag !== "all" || status !== "all";

  if (loading || (run && isLoading) || !config) return <Skeleton className="h-[600px]" />;
  if (!run)
    return (
      <Card>
        <Empty icon={<ListChecks className="size-5" />} title="No reviews yet" body="Start a run to classify reviews." action={<NewRunButton label="Start a run" />} />
      </Card>
    );

  const toggleSort = () => {
    const next = new URLSearchParams(params);
    if (sort !== "min_confidence") {
      next.set("sort", "min_confidence");
      next.delete("dir");
    } else if (dir === 1) next.set("dir", "desc");
    else {
      next.delete("sort");
      next.delete("dir");
    }
    setParams(next, { replace: true });
  };

  return (
    <div>
      <PageHeader
        title="Reviews"
        subtitle={`${filtered.length} of ${rows?.length ?? 0} reviews`}
        actions={
          <a href={api.exportUrl(run.id)} download>
            <Button icon={<Download className="size-4" />}>Export CSV</Button>
          </a>
        }
      />
      <ErrorBanner error={error} />

      <div className="flex flex-wrap gap-2 mb-4">
        <div className="relative flex-1 min-w-[220px] basis-full md:basis-auto">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-3" />
          <input className={cx(inputCls, "pl-9 w-full")} placeholder="Search review text or ID…" value={q} onChange={(e) => set("q", e.target.value, "")} />
        </div>
        <Select className="w-auto" label="Topic" value={topic} onChange={(v) => set("topic", v)}
          options={[{ value: "all", label: "All topics" }, ...config.topics.map((t) => ({ value: t, label: humanize(t) }))]} />
        <Select className="w-auto" label="Sentiment" value={sentiment} onChange={(v) => set("sentiment", v)}
          options={[{ value: "all", label: "All sentiment" }, ...config.sentiments.map((s) => ({ value: s, label: humanize(s) }))]} />
        <Select className="w-auto" label="Flags" value={flag} onChange={(v) => set("flag", v)}
          options={[{ value: "all", label: "Any flags" }, { value: "defect", label: "Defect" }, { value: "refund", label: "Refund / return" }, { value: "none", label: "No flags" }]} />
        <Select className="w-auto" label="Status" value={status} onChange={(v) => set("status", v)}
          options={[
            { value: "all", label: "Any status" },
            { value: "needs_review", label: "Needs review" },
            { value: "auto", label: "Auto-accepted" },
            { value: "reviewed", label: "Reviewed" },
            { value: "corrected", label: "Corrected" },
            { value: "error", label: "Errors" },
          ]} />
        {anyFilter && (
          <Button variant="ghost" onClick={() => { setParams(new URLSearchParams(), { replace: true }); setPage(0); }}>
            Clear
          </Button>
        )}
      </div>

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-2/60 text-ink-2 text-[13px]">
              <tr className="border-b border-line">
                <th className="text-left font-medium px-4 py-2.5 w-[42%]">Review</th>
                <th className="text-left font-medium px-3 py-2.5">Topic</th>
                <th className="text-left font-medium px-3 py-2.5">Sentiment</th>
                <th className="text-left font-medium px-3 py-2.5">Flags</th>
                <th className="text-left font-medium px-3 py-2.5">
                  <button className="inline-flex items-center gap-1 hover:text-ink" onClick={toggleSort}>
                    Confidence
                    {sort === "min_confidence" && (dir === 1 ? <ArrowUp className="size-3.5" /> : <ArrowDown className="size-3.5" />)}
                  </button>
                </th>
                <th className="text-left font-medium px-3 py-2.5">Status</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr
                  key={r.review_id}
                  tabIndex={0}
                  onClick={() => setOpenId(r.review_id)}
                  onKeyDown={(e) => e.key === "Enter" && setOpenId(r.review_id)}
                  className="border-b border-line last:border-0 hover:bg-surface-2/60 cursor-pointer"
                >
                  <td className="px-4 py-3">
                    <div className="text-ink line-clamp-2">{r.text}</div>
                    <div className="text-xs text-ink-3 mt-0.5 font-mono">{r.review_id}</div>
                  </td>
                  <td className="px-3 py-3"><TopicTag value={r.topic} /></td>
                  <td className="px-3 py-3"><SentimentPill value={r.sentiment} /></td>
                  <td className="px-3 py-3"><Flags row={r} /></td>
                  <td className="px-3 py-3"><ConfidenceMeter value={r.min_confidence} threshold={run.threshold} /></td>
                  <td className="px-3 py-3"><ReviewState row={r} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {visible.length === 0 && (
            <Empty icon={<Search className="size-5" />} title="No reviews match" body="Try a different search or clear the filters." />
          )}
        </div>
        {pages > 1 && (
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-line text-[13px] text-ink-2">
            <span className="tabular">
              {page * PAGE + 1}–{Math.min(filtered.length, (page + 1) * PAGE)} of {filtered.length}
            </span>
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)} icon={<ChevronLeft className="size-4" />} aria-label="Previous page" />
              <Button size="sm" variant="ghost" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} icon={<ChevronRight className="size-4" />} aria-label="Next page" />
            </div>
          </div>
        )}
      </Card>

      {openRow && <ReviewDrawer key={openRow.review_id} row={openRow} run={run} config={config} onClose={() => setOpenId(null)} />}
    </div>
  );
}

function ReviewDrawer({ row, run, config, onClose }: { row: DecisionRow; run: Run; config: AppConfig; onClose: () => void }) {
  const [value, setValue] = useState<Labels>(labelsOf(row));
  const patch = usePatchDecision(run.id);
  const toast = useToast();
  const dirty = isDirty(row, value);
  const save = (reviewed = true) =>
    patch.mutate(
      { reviewId: row.review_id, body: { ...value, reviewed } },
      {
        onSuccess: (r) => {
          toast({ tone: "good", text: r.corrected ? "Correction saved" : "Marked as reviewed" });
          onClose();
        },
      },
    );
  const decided = row.topic != null;
  return (
    <Drawer
      open
      onClose={onClose}
      title={<span className="font-mono text-sm">{row.review_id}</span>}
      footer={
        decided && (
          <>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="primary" loading={patch.isPending} onClick={() => save()}>
              {dirty ? "Save correction" : row.reviewed ? "Save" : "Approve"}
            </Button>
          </>
        )
      }
    >
      <div className="space-y-5">
        <div className="flex items-center gap-2"><ReviewState row={row} /></div>
        <blockquote className="text-[15px] leading-relaxed text-ink bg-surface-2 border border-line rounded-xl p-4">{row.text}</blockquote>
        {row.error && <ErrorBanner error={row.error} />}
        {decided && <DecisionEditor row={row} value={value} onChange={setValue} config={config} threshold={run.threshold} />}
        <ErrorBanner error={patch.error} />
        {decided && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[13px] pt-2 border-t border-line">
            <dt className="text-ink-3">Model</dt><dd className="text-right text-ink-2 truncate">{row.model}</dd>
            <dt className="text-ink-3">Latency</dt><dd className="text-right tabular text-ink-2">{ms(row.latency_ms)}</dd>
            <dt className="text-ink-3">Tokens in / out</dt><dd className="text-right tabular text-ink-2">{row.input_tokens} / {row.output_tokens}</dd>
            <dt className="text-ink-3">Cost</dt><dd className="text-right tabular text-ink-2">{usd(row.cost_usd)}</dd>
            <dt className="text-ink-3">Lowest confidence</dt><dd className="text-right tabular text-ink-2">{pct(row.min_confidence, 1)}</dd>
          </dl>
        )}
      </div>
    </Drawer>
  );
}
