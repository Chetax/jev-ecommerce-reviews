import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Database, FileSpreadsheet, FileUp, Plus, Sheet, UploadCloud } from "lucide-react";
import { useRef, useState, type DragEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Run } from "../lib/api";
import { pct } from "../lib/format";
import { useConfig, useSelectedRun } from "../lib/hooks";
import { Button, Dialog, ErrorBanner, Select, cx, inputCls, useToast } from "./ui";

type Source = Run["source"];

function countRows(text: string) {
  return Math.max(0, text.split(/\r?\n/).filter((l) => l.trim()).length - 1);
}

export function NewRunButton({ variant = "primary", label = "New run" }: { variant?: "primary" | "secondary"; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant={variant} icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>
        {label}
      </Button>
      <NewRunDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function NewRunDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: config } = useConfig();
  const { setRunId } = useSelectedRun();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);

  const [source, setSource] = useState<Source>("sample");
  const [model, setModel] = useState("bedrock");
  const [name, setName] = useState("");
  const [threshold, setThreshold] = useState<number | null>(null);
  const [file, setFile] = useState<{ name: string; text: string } | null>(null);
  const [drag, setDrag] = useState(false);
  const thr = threshold ?? config?.threshold ?? 0.8;

  const create = useMutation({
    mutationFn: () =>
      api.createRun({
        source,
        model,
        threshold: thr,
        name: name.trim() || (source === "csv" ? file?.name : undefined),
        csv_text: source === "csv" ? file?.text : undefined,
      }),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ["runs"] });
      setRunId(run.id);
      toast({ tone: "good", text: `Started “${run.name}” · ${run.total} reviews` });
      onClose();
      setFile(null);
      setName("");
      navigate("/");
    },
  });

  const readFile = async (f: File | undefined) => {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".csv")) {
      toast({ tone: "critical", text: "Please choose a .csv file." });
      return;
    }
    setFile({ name: f.name.replace(/\.csv$/i, ""), text: await f.text() });
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    readFile(e.dataTransfer.files[0]);
  };

  const sources: { value: Source; title: string; body: string; icon: ReactNode; disabled?: boolean }[] = [
    { value: "sample", title: "Sample data", body: "48 labeled reviews", icon: <Database className="size-4" /> },
    { value: "csv", title: "Upload CSV", body: "review_id, text columns", icon: <FileUp className="size-4" /> },
    {
      value: "sheet",
      title: "Google Sheet",
      body: config?.sheets_enabled ? "From your configured sheet" : "Set SHEET_ID to enable",
      icon: <Sheet className="size-4" />,
      disabled: !config?.sheets_enabled,
    },
  ];
  const canSubmit = source !== "csv" || !!file;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New classification run"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={create.isPending} disabled={!canSubmit} onClick={() => create.mutate()}>
            Start run
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <fieldset>
          <legend className="text-[13px] font-medium mb-2">Source</legend>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {sources.map((s) => (
              <button
                key={s.value}
                type="button"
                disabled={s.disabled}
                onClick={() => setSource(s.value)}
                aria-pressed={source === s.value}
                className={cx(
                  "text-left rounded-xl border p-3 transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
                  source === s.value ? "border-accent bg-accent-soft" : "border-line-strong hover:bg-surface-2",
                )}
              >
                <div className={cx("flex items-center gap-2 text-sm font-medium", source === s.value ? "text-accent" : "text-ink")}>
                  {s.icon}
                  {s.title}
                </div>
                <div className="text-xs text-ink-2 mt-1">{s.body}</div>
              </button>
            ))}
          </div>
        </fieldset>

        {source === "csv" && (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
            onClick={() => fileRef.current?.click()}
            className={cx(
              "rounded-xl border-2 border-dashed p-6 text-center cursor-pointer transition-colors",
              drag ? "border-accent bg-accent-soft" : "border-line-strong hover:bg-surface-2",
            )}
          >
            <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => readFile(e.target.files?.[0])} />
            {file ? (
              <div className="flex items-center justify-center gap-2 text-sm">
                <FileSpreadsheet className="size-5 text-accent" />
                <span className="font-medium">{file.name}.csv</span>
                <span className="text-ink-2">· {countRows(file.text)} rows</span>
              </div>
            ) : (
              <>
                <UploadCloud className="size-6 mx-auto text-ink-3" />
                <p className="text-sm mt-2"><span className="font-medium text-accent">Choose a file</span> or drag it here</p>
                <p className="text-xs text-ink-2 mt-1">Needs a <code>text</code> column. Optional: <code>review_id</code>, plus labels to benchmark against.</p>
              </>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <label className="block">
            <span className="text-[13px] font-medium">Model</span>
            <Select
              className="mt-1.5 w-full"
              label="Model"
              value={model}
              onChange={setModel}
              options={(config?.models ?? []).map((m) => ({
                value: m.spec,
                label: m.disabled ? `${m.label} (needs TypeSafe key)` : m.label,
                disabled: m.disabled,
              }))}
            />
          </label>
          <label className="block">
            <span className="text-[13px] font-medium">Name <span className="text-ink-3 font-normal">(optional)</span></span>
            <input className={cx(inputCls, "mt-1.5 w-full")} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. October reviews" />
          </label>
        </div>

        <label className="block">
          <div className="flex justify-between text-[13px]">
            <span className="font-medium">Review threshold</span>
            <span className="tabular text-ink-2">{pct(thr)}</span>
          </div>
          <input
            type="range"
            min={0.5}
            max={0.99}
            step={0.01}
            value={thr}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-full mt-2 accent-[var(--accent)]"
          />
          <p className="text-xs text-ink-2 mt-1">Reviews where any field's confidence is below this go to the review queue.</p>
        </label>

        <ErrorBanner error={create.error} />
      </div>
    </Dialog>
  );
}
