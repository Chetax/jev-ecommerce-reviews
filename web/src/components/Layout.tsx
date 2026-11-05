import { Activity, ExternalLink, FlaskConical, Inbox, LayoutDashboard, ListChecks, Menu, Monitor, Moon, PlayCircle, Sun, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { modelLabel, timeAgo } from "../lib/format";
import { useConfig, useSelectedRun, useTheme, type ThemePref } from "../lib/hooks";
import { NewRunButton } from "./NewRun";
import { Progress, RunStatusBadge, Select, cx } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/reviews", label: "Reviews", icon: ListChecks },
  { to: "/queue", label: "Review queue", icon: Inbox, badge: true },
  { to: "/runs", label: "Runs", icon: PlayCircle },
  { to: "/benchmark", label: "Benchmark", icon: FlaskConical },
];

function ThemeSwitch() {
  const [pref, setPref] = useTheme();
  const opts: { v: ThemePref; icon: ReactNode; label: string }[] = [
    { v: "light", icon: <Sun className="size-3.5" />, label: "Light" },
    { v: "system", icon: <Monitor className="size-3.5" />, label: "System" },
    { v: "dark", icon: <Moon className="size-3.5" />, label: "Dark" },
  ];
  return (
    <div role="radiogroup" aria-label="Theme" className="flex gap-0.5 p-0.5 rounded-lg bg-surface-2 border border-line">
      {opts.map((o) => (
        <button
          key={o.v}
          role="radio"
          aria-checked={pref === o.v}
          title={o.label}
          onClick={() => setPref(o.v)}
          className={cx("flex-1 h-7 grid place-items-center rounded-md", pref === o.v ? "bg-surface shadow-card text-ink" : "text-ink-3 hover:text-ink")}
        >
          {o.icon}
        </button>
      ))}
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { run } = useSelectedRun();
  const { data: config } = useConfig();
  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2.5 px-4 h-14">
        <div className="size-7 rounded-lg bg-accent grid place-items-center">
          <svg viewBox="0 0 32 32" className="size-4"><path d="M9 16.5l4.5 4.5L23 11.5" stroke="white" strokeWidth="3.5" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">Review Decisions</div>
          <div className="text-[11px] text-ink-3">Typed review triage</div>
        </div>
      </div>
      <nav className="px-2 py-2 space-y-0.5 flex-1">
        {NAV.map(({ to, label, icon: Icon, badge }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              cx(
                "flex items-center gap-2.5 h-9 px-3 rounded-lg text-sm transition-colors",
                isActive ? "bg-surface text-ink font-medium shadow-card border border-line" : "text-ink-2 hover:text-ink hover:bg-surface-2 border border-transparent",
              )
            }
          >
            <Icon className="size-4" />
            <span className="flex-1">{label}</span>
            {badge && run && run.pending_review > 0 && (
              <span className="tabular text-[11px] font-semibold px-1.5 min-w-5 h-5 grid place-items-center rounded-md bg-warning-soft text-warning-ink">
                {run.pending_review}
              </span>
            )}
          </NavLink>
        ))}
        {config?.tracing_url && (
          <a
            href={config.tracing_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2.5 h-9 px-3 rounded-lg text-sm text-ink-2 hover:text-ink hover:bg-surface-2 border border-transparent transition-colors"
          >
            <Activity className="size-4" />
            <span className="flex-1">Traces</span>
            <ExternalLink className="size-3.5 text-ink-3" />
          </a>
        )}
      </nav>
      <div className="p-3 space-y-3 border-t border-line">
        {config && (
          <div className="text-[11px] text-ink-3 leading-relaxed px-1">
            <div className="truncate">Bedrock · {config.bedrock_model.replace("anthropic.", "")}</div>
            <div>{config.aws_region} · Jev {config.jev_enabled ? "on" : "off"}</div>
          </div>
        )}
        <ThemeSwitch />
      </div>
    </div>
  );
}

function RunPicker() {
  const { run, runs, setRunId } = useSelectedRun();
  if (!runs.length) return null;
  return (
    <div className="flex items-center gap-3 min-w-0">
      <Select
        label="Run"
        className="w-[min(340px,52vw)]"
        value={run?.id ?? ""}
        onChange={setRunId}
        options={runs.map((r) => ({ value: r.id, label: `${r.name} · ${modelLabel(r.model)} · ${timeAgo(r.created_at)}` }))}
      />
      {run && run.status !== "done" && <RunStatusBadge status={run.status} />}
    </div>
  );
}

export function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { run } = useSelectedRun();
  const loc = useLocation();
  const showPicker = !["/runs", "/benchmark"].includes(loc.pathname);
  const active = run && (run.status === "running" || run.status === "queued");
  return (
    <div className="min-h-dvh flex">
      <aside className="hidden lg:block w-60 shrink-0 border-r border-line bg-page sticky top-0 h-dvh">
        <Sidebar />
      </aside>
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/30" onClick={() => setMobileOpen(false)} />
          <aside className="anim-slide absolute left-0 top-0 h-full w-64 bg-page border-r border-line">
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-30 h-14 flex items-center gap-3 px-4 lg:px-8 border-b border-line bg-page/85 backdrop-blur">
          <button className="lg:hidden p-1.5 -ml-1.5 rounded-md text-ink-2 hover:bg-surface-2" onClick={() => setMobileOpen((o) => !o)} aria-label="Menu">
            {mobileOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
          <div className="flex-1 min-w-0">{showPicker && <RunPicker />}</div>
          <NewRunButton />
        </header>
        {active && showPicker && (
          <div className="px-4 lg:px-8 py-2.5 border-b border-line bg-accent-soft/60 flex items-center gap-4 text-[13px]">
            <span className="text-ink font-medium whitespace-nowrap">Classifying… {run.done + run.failed} / {run.total}</span>
            <div className="flex-1 max-w-md"><Progress value={(run.done + run.failed) / Math.max(1, run.total)} /></div>
          </div>
        )}
        <main className="flex-1 px-4 lg:px-8 py-6 lg:py-8 max-w-[1400px] w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-ink-2 mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
