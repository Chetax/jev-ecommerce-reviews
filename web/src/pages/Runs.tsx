import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, MoreHorizontal, PlayCircle, Sheet, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader } from "../components/Layout";
import { NewRunButton } from "../components/NewRun";
import { Button, Card, Dialog, Empty, Progress, RunStatusBadge, Skeleton, cx, useToast } from "../components/ui";
import { api, type Run } from "../lib/api";
import { modelLabel, num, timeAgo, usd } from "../lib/format";
import { useConfig, useSelectedRun } from "../lib/hooks";

const SOURCE: Record<Run["source"], string> = { sample: "Sample", csv: "CSV upload", sheet: "Google Sheet" };

function RunMenu({ run, onDelete }: { run: Run; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { data: config } = useConfig();
  const toast = useToast();
  const push = useMutation({
    mutationFn: () => api.pushSheet(run.id),
    onSuccess: (r) => toast({ tone: "good", text: `Wrote decisions to the “${r.tab}” tab` }),
    onError: (e) => toast({ tone: "critical", text: e.message }),
  });
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  const busy = run.status === "running" || run.status === "queued";
  const item = "w-full flex items-center gap-2 px-3 h-9 text-sm text-left rounded-md hover:bg-surface-2 disabled:opacity-50 disabled:pointer-events-none";
  return (
    <div className="relative" ref={ref} onClick={(e) => e.stopPropagation()}>
      <Button size="sm" variant="ghost" aria-label="Run actions" onClick={() => setOpen((o) => !o)} icon={<MoreHorizontal className="size-4" />} />
      {open && (
        <div className="anim-fade absolute right-0 top-9 z-20 w-52 p-1 rounded-xl border border-line bg-surface shadow-pop">
          <a href={api.exportUrl(run.id)} download className={item} onClick={() => setOpen(false)}>
            <Download className="size-4 text-ink-2" /> Export CSV
          </a>
          <button className={item} disabled={!config?.sheets_enabled || busy || push.isPending} onClick={() => { push.mutate(); setOpen(false); }}
            title={config?.sheets_enabled ? undefined : "Set SHEET_ID to enable"}>
            <Sheet className="size-4 text-ink-2" /> Write to Google Sheet
          </button>
          <button className={cx(item, "text-critical-ink")} disabled={busy} onClick={() => { setOpen(false); onDelete(); }}>
            <Trash2 className="size-4" /> Delete run
          </button>
        </div>
      )}
    </div>
  );
}

export function Runs() {
  const { runs, loading, setRunId } = useSelectedRun();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [confirm, setConfirm] = useState<Run | null>(null);
  const del = useMutation({
    mutationFn: (id: string) => api.deleteRun(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      toast({ tone: "neutral", text: "Run deleted" });
      setConfirm(null);
    },
  });

  if (loading) return <Skeleton className="h-96" />;

  return (
    <div>
      <PageHeader title="Runs" subtitle="Every batch of reviews you've classified" actions={<NewRunButton variant="secondary" />} />
      {!runs.length ? (
        <Card>
          <Empty icon={<PlayCircle className="size-5" />} title="No runs yet" body="A run classifies a batch of reviews with the model you pick." action={<NewRunButton label="Start a run" />} />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-2/60 text-ink-2 text-[13px]">
                <tr className="border-b border-line">
                  <th className="text-left font-medium px-4 py-2.5">Run</th>
                  <th className="text-left font-medium px-3 py-2.5">Status</th>
                  <th className="text-left font-medium px-3 py-2.5 w-48">Progress</th>
                  <th className="text-right font-medium px-3 py-2.5">To review</th>
                  <th className="text-right font-medium px-3 py-2.5">Cost</th>
                  <th className="px-3 py-2.5 w-12" />
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const processed = r.done + r.failed;
                  return (
                    <tr
                      key={r.id}
                      tabIndex={0}
                      className="border-b border-line last:border-0 hover:bg-surface-2/60 cursor-pointer"
                      onClick={() => { setRunId(r.id); navigate("/"); }}
                      onKeyDown={(e) => { if (e.key === "Enter") { setRunId(r.id); navigate("/"); } }}
                    >
                      <td className="px-4 py-3">
                        <div className="font-medium text-ink">{r.name}</div>
                        <div className="text-xs text-ink-2 mt-0.5">
                          {SOURCE[r.source]} · {modelLabel(r.model)} · {timeAgo(r.created_at)}
                        </div>
                      </td>
                      <td className="px-3 py-3"><RunStatusBadge status={r.status} /></td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-2">
                          <Progress value={processed / Math.max(1, r.total)} tone={r.failed && r.failed === processed ? "critical" : "accent"} />
                          <span className="tabular text-xs text-ink-2 whitespace-nowrap">{num(processed)}/{num(r.total)}</span>
                        </div>
                        {r.failed > 0 && <div className="text-xs text-critical-ink mt-1">{r.failed} failed</div>}
                      </td>
                      <td className="px-3 py-3 text-right tabular">{r.pending_review || <span className="text-ink-3">0</span>}</td>
                      <td className="px-3 py-3 text-right tabular text-ink-2">{usd(r.cost_usd)}</td>
                      <td className="px-3 py-3"><RunMenu run={r} onDelete={() => setConfirm(r)} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Dialog
        open={!!confirm}
        onClose={() => setConfirm(null)}
        title="Delete run?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
            <Button variant="danger" loading={del.isPending} onClick={() => confirm && del.mutate(confirm.id)} icon={<Trash2 className="size-4" />}>
              Delete
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-2">
          “{confirm?.name}” and its {confirm?.total} decisions, including any human corrections, will be permanently removed. Export it first if you need the data.
        </p>
      </Dialog>
    </div>
  );
}
