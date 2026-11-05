import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type DecisionRow, type Run } from "./api";
import { storage } from "./format";

export const useConfig = () => useQuery({ queryKey: ["config"], queryFn: api.config, staleTime: 60_000 });

const isActive = (r: Pick<Run, "status">) => r.status === "queued" || r.status === "running";

export const useRuns = () =>
  useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: (q) => (q.state.data?.some(isActive) ? 1000 : false),
  });

export function useDecisions(run: Run | undefined) {
  return useQuery({
    queryKey: ["decisions", run?.id],
    queryFn: () => api.decisions(run!.id),
    enabled: !!run,
    refetchInterval: run && isActive(run) ? 1500 : false,
  });
}

export function usePatchDecision(runId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { reviewId: string; body: Parameters<typeof api.patchDecision>[2] }) =>
      api.patchDecision(runId!, v.reviewId, v.body),
    onSuccess: (row) => {
      qc.setQueryData<DecisionRow[]>(["decisions", runId], (rows) =>
        rows?.map((r) => (r.review_id === row.review_id ? row : r)),
      );
      qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

/* ---------- selected run (shared across pages) ---------- */
type Ctx = { run: Run | undefined; runs: Run[]; setRunId: (id: string) => void; loading: boolean };
const RunCtx = createContext<Ctx>({ run: undefined, runs: [], setRunId: () => {}, loading: true });
export const useSelectedRun = () => useContext(RunCtx);

export function RunProvider({ children }: { children: ReactNode }) {
  const { data: runs = [], isLoading } = useRuns();
  const [runId, setRunIdState] = useState<string | null>(() => storage.get("runId"));
  const setRunId = (id: string) => {
    setRunIdState(id);
    storage.set("runId", id);
  };
  const run = useMemo(
    () => runs.find((r) => r.id === runId) ?? runs.find((r) => r.status === "done") ?? runs[0],
    [runs, runId],
  );
  useEffect(() => {
    if (run && run.id !== runId) setRunIdState(run.id);
  }, [run, runId]);
  return <RunCtx.Provider value={{ run, runs, setRunId, loading: isLoading }}>{children}</RunCtx.Provider>;
}

/* ---------- theme ---------- */
export type ThemePref = "system" | "light" | "dark";
export function useTheme(): [ThemePref, (t: ThemePref) => void] {
  const [pref, setPref] = useState<ThemePref>(() => (storage.get("theme") as ThemePref) || "system");
  useEffect(() => {
    const el = document.documentElement;
    if (pref === "system") delete el.dataset.theme;
    else el.dataset.theme = pref;
    storage.set("theme", pref === "system" ? null : pref);
  }, [pref]);
  return [pref, setPref];
}
