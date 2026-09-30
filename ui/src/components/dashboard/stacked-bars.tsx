import { useMemo } from 'react';

interface HourPoint {
  hour: string;
  knx: number;
  bacnet: number;
}

interface Props {
  data: HourPoint[];
  height?: number;
}

const PAD = { top: 12, right: 16, bottom: 32, left: 44 };

export function StackedBars({ data, height = 240 }: Props) {
  const width = 800; // sera stretch via viewBox
  const chartW = width - PAD.left - PAD.right;
  const chartH = height - PAD.top - PAD.bottom;

  const { max, bars } = useMemo(() => {
    if (data.length === 0) return { max: 1, bars: [] as any[] };
    const max = Math.max(1, ...data.map((d) => d.knx + d.bacnet));
    const barW = chartW / Math.max(1, data.length);
    const bars = data.map((d, i) => {
      const x = PAD.left + i * barW + barW * 0.15;
      const w = barW * 0.7;
      const totalH = ((d.knx + d.bacnet) / max) * chartH;
      const knxH = (d.knx / max) * chartH;
      const bacnetH = (d.bacnet / max) * chartH;
      const yTop = PAD.top + chartH - totalH;
      const label = d.hour.slice(11, 16); // HH:MM
      return {
        x, w, knxH, bacnetH, yTop,
        knxY: yTop + bacnetH,
        bacnetY: yTop,
        label,
        knx: d.knx,
        bacnet: d.bacnet,
      };
    });
    return { max, bars };
  }, [data, chartW, chartH]);

  const yTicks = 4;
  const ticks = Array.from({ length: yTicks + 1 }, (_, i) => {
    const v = (max / yTicks) * i;
    const y = PAD.top + chartH - (v / max) * chartH;
    return { v: Math.round(v), y };
  });

  return (
    <div className="w-full">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" preserveAspectRatio="none">
        {/* Grid */}
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={PAD.left} x2={width - PAD.right} y1={t.y} y2={t.y}
                  stroke="currentColor" strokeOpacity="0.1" />
            <text x={PAD.left - 6} y={t.y + 3} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.5">
              {t.v}
            </text>
          </g>
        ))}
        {/* Bars */}
        {bars.map((b, i) => (
          <g key={i}>
            {b.bacnetH > 0 && (
              <rect x={b.x} y={b.bacnetY} width={b.w} height={b.bacnetH}
                    fill="#f59e0b" opacity="0.85">
                <title>{`${b.label} — BACnet: ${b.bacnet}`}</title>
              </rect>
            )}
            {b.knxH > 0 && (
              <rect x={b.x} y={b.knxY} width={b.w} height={b.knxH}
                    fill="#0ea5e9" opacity="0.85">
                <title>{`${b.label} — KNX: ${b.knx}`}</title>
              </rect>
            )}
            {i % Math.ceil(bars.length / 12) === 0 && (
              <text x={b.x + b.w / 2} y={height - 12} fontSize="10" textAnchor="middle"
                    fill="currentColor" opacity="0.6">
                {b.label}
              </text>
            )}
          </g>
        ))}
      </svg>
      <div className="mt-2 flex items-center justify-center gap-4 text-xs">
        <span className="flex items-center gap-1">
          <span className="size-3 rounded-sm bg-[#0ea5e9]" /> KNX
        </span>
        <span className="flex items-center gap-1">
          <span className="size-3 rounded-sm bg-[#f59e0b]" /> BACnet
        </span>
      </div>
    </div>
  );
}
