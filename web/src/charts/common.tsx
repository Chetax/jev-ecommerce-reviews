import { useState, type ReactNode } from "react";
import { BarChart3, Table2 } from "lucide-react";
import { Card, CardHeader, Segmented } from "../components/ui";

export const AXIS = { stroke: "var(--axis)", tick: { fill: "var(--ink-3)", fontSize: 12 }, tickLine: false } as const;
export const GRID = { stroke: "var(--grid)", strokeWidth: 1 } as const;
export const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

export function Legend({ items }: { items: { label: string; color: string; shape?: "dot" | "line" | "square" }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-2">
      {items.map((i) => (
        <li key={i.label} className="inline-flex items-center gap-1.5">
          {i.shape === "line" ? (
            <span className="w-3.5 h-0.5 rounded-full" style={{ background: i.color }} />
          ) : (
            <span className={i.shape === "square" ? "size-2.5 rounded-[3px]" : "size-2.5 rounded-full"} style={{ background: i.color }} />
          )}
          {i.label}
        </li>
      ))}
    </ul>
  );
}

type TipRow = { label: string; value: string; color?: string };

export function TooltipBox({ title, rows }: { title?: ReactNode; rows: TipRow[] }) {
  return (
    <div className="rounded-lg border border-line bg-surface shadow-pop px-3 py-2 text-[13px] min-w-40">
      {title && <div className="font-medium text-ink mb-1">{title}</div>}
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-4 py-0.5">
          <span className="inline-flex items-center gap-1.5 text-ink-2">
            {r.color && <span className="size-2 rounded-full" style={{ background: r.color }} />}
            {r.label}
          </span>
          <span className="tabular text-ink font-medium">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

export interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  align?: "left" | "right";
}

export function DataTable<T>({ rows, columns }: { rows: T[]; columns: Column<T>[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-ink-3 border-b border-line">
            {columns.map((c) => (
              <th key={c.key} className={`font-medium py-2 px-2 ${c.align === "right" ? "text-right" : "text-left"}`}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line last:border-0">
              {columns.map((c) => (
                <td key={c.key} className={`py-2 px-2 ${c.align === "right" ? "text-right" : ""}`}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A card with a chart/table toggle so values are never gated behind color or hover. */
export function ChartCard({ title, subtitle, legend, chart, table, className, actions }: {
  title: string;
  subtitle?: ReactNode;
  legend?: ReactNode;
  chart: ReactNode;
  table: ReactNode;
  className?: string;
  actions?: ReactNode;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <Card className={className}>
      <CardHeader
        title={title}
        subtitle={subtitle}
        actions={
          <>
            {actions}
            <Segmented
              size="sm"
              label={`${title} view`}
              value={view}
              onChange={setView}
              options={[
                { value: "chart", label: <BarChart3 className="size-3.5" aria-label="Chart" />, hint: "Chart" },
                { value: "table", label: <Table2 className="size-3.5" aria-label="Table" />, hint: "Table" },
              ]}
            />
          </>
        }
      />
      <div className="px-5 pb-5">
        {view === "chart" ? (
          <>
            {legend && <div className="mb-3">{legend}</div>}
            {chart}
          </>
        ) : (
          table
        )}
      </div>
    </Card>
  );
}
