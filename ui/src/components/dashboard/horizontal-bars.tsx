interface Op { protocol: string; operation: string; count: number; }
interface Props { data: Op[]; max?: number; }

const COLORS: Record<string, string> = {
  knx: '#0ea5e9',
  bacnet: '#f59e0b',
  modbus: '#10b981',
};

export function HorizontalBars({ data, max = 10 }: Props) {
  const rows = data.slice(0, max);
  const maxCount = Math.max(1, ...rows.map((r) => r.count));

  return (
    <div className="flex flex-col gap-1.5">
      {rows.map((r, i) => {
        const pct = (r.count / maxCount) * 100;
        const color = COLORS[r.protocol] || '#94a3b8';
        return (
          <div key={i} className="flex items-center gap-3 text-xs">
            <div className="w-16 shrink-0 truncate uppercase text-[color:var(--color-muted-foreground)]">
              {r.protocol}
            </div>
            <div className="flex-1 truncate font-mono">{r.operation}</div>
            <div className="relative h-5 w-40 shrink-0 rounded bg-[color:var(--color-muted)]">
              <div className="h-full rounded transition-all" style={{ width: `${pct}%`, background: color, opacity: 0.85 }} />
            </div>
            <div className="w-16 shrink-0 text-right font-medium tabular-nums">
              {r.count.toLocaleString('fr-FR')}
            </div>
          </div>
        );
      })}
    </div>
  );
}
