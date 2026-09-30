interface Slice { name: string; count: number; percent: number; color: string; }
interface Props { data: Array<{name: string; count: number; percent: number}>; size?: number; }

const COLORS: Record<string, string> = {
  KNX: '#0ea5e9',
  BACNET: '#f59e0b',
  MODBUS: '#10b981',
};

export function Donut({ data, size = 160 }: Props) {
  const slices: Slice[] = data.map((d) => ({
    ...d,
    color: COLORS[d.name] || '#94a3b8',
  }));
  const total = slices.reduce((s, x) => s + x.count, 0) || 1;
  const r = size / 2 - 8;
  const cx = size / 2;
  const cy = size / 2;
  let acc = 0;
  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {slices.map((s, i) => {
          const start = (acc / total) * 2 * Math.PI - Math.PI / 2;
          acc += s.count;
          const end = (acc / total) * 2 * Math.PI - Math.PI / 2;
          const large = end - start > Math.PI ? 1 : 0;
          const x1 = cx + r * Math.cos(start);
          const y1 = cy + r * Math.sin(start);
          const x2 = cx + r * Math.cos(end);
          const y2 = cy + r * Math.sin(end);
          const path = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
          return <path key={i} d={path} fill={s.color} opacity="0.9">
            <title>{`${s.name}: ${s.count} (${s.percent}%)`}</title>
          </path>;
        })}
        <circle cx={cx} cy={cy} r={r * 0.55} fill="var(--color-card)" />
        <text x={cx} y={cy - 4} textAnchor="middle" fontSize="14" fill="currentColor" fontWeight="600">
          {total.toLocaleString('fr-FR')}
        </text>
        <text x={cx} y={cy + 12} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.6">
          trames
        </text>
      </svg>
      <div className="flex flex-col gap-1 text-xs">
        {slices.map((s) => (
          <div key={s.name} className="flex items-center gap-2">
            <span className="size-3 rounded-sm" style={{ background: s.color }} />
            <span className="font-medium">{s.name}</span>
            <span className="text-[color:var(--color-muted-foreground)]">
              {s.percent}% ({s.count.toLocaleString('fr-FR')})
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
