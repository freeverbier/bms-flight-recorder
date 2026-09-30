// LineChart SVG minimal — pas de dépendance externe.
// Auto-scale X (temps) + Y, tooltip au survol, grille légère.

import { useEffect, useMemo, useRef, useState } from 'react';
import type { KnxHistoryPoint } from '@/lib/types';

interface LineChartProps {
  points: KnxHistoryPoint[];
  unit?: string;
  height?: number;
  color?: string;
}

const PADDING = { top: 10, right: 16, bottom: 28, left: 48 };
const CIRCLE_R = 3;

export function LineChart({ points, unit = '', height = 320, color = '#0ea5e9' }: LineChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [width, setWidth] = useState(800);

  // Observer pour resize responsive
  useEffect(() => {
    if (!svgRef.current?.parentElement) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        setWidth(Math.max(300, e.contentRect.width));
      }
    });
    ro.observe(svgRef.current.parentElement);
    return () => ro.disconnect();
  }, []);

  const validPoints = useMemo(
    () => points.filter((p) => p.value !== null && Number.isFinite(p.value)),
    [points],
  );

  const stats = useMemo(() => {
    if (validPoints.length === 0) return null;
    let minV = Infinity, maxV = -Infinity;
    for (const p of validPoints) {
      if (p.value! < minV) minV = p.value!;
      if (p.value! > maxV) maxV = p.value!;
    }
    if (minV === maxV) {
      // Étirer un peu pour ne pas afficher une ligne plate collée au bord
      minV -= 1;
      maxV += 1;
    } else {
      // Marge 5% de chaque côté
      const range = maxV - minV;
      minV -= range * 0.05;
      maxV += range * 0.05;
    }
    const tMin = new Date(validPoints[0].ts).getTime();
    const tMax = new Date(validPoints[validPoints.length - 1].ts).getTime();
    return { minV, maxV, tMin, tMax };
  }, [validPoints]);

  if (!stats) {
    return (
      <div
        className="grid place-items-center rounded-md border border-dashed border-[color:var(--color-border)] text-sm text-[color:var(--color-muted-foreground)]"
        style={{ height }}
      >
        Aucun point à afficher.
      </div>
    );
  }

  const innerW = width - PADDING.left - PADDING.right;
  const innerH = height - PADDING.top - PADDING.bottom;

  const scaleX = (ts: string) => {
    const t = new Date(ts).getTime();
    return PADDING.left + ((t - stats.tMin) / Math.max(1, stats.tMax - stats.tMin)) * innerW;
  };
  const scaleY = (v: number) =>
    PADDING.top + innerH - ((v - stats.minV) / (stats.maxV - stats.minV)) * innerH;

  // Path de la ligne (traits interrompus sur les points null)
  const pathParts: string[] = [];
  let pen = false;
  for (const p of points) {
    if (p.value === null || !Number.isFinite(p.value)) {
      pen = false;
      continue;
    }
    const x = scaleX(p.ts);
    const y = scaleY(p.value);
    pathParts.push(`${pen ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`);
    pen = true;
  }
  const linePath = pathParts.join(' ');

  // Ticks Y : 5 niveaux
  const yTicks: { v: number; y: number }[] = [];
  for (let i = 0; i <= 4; i++) {
    const v = stats.minV + ((stats.maxV - stats.minV) * i) / 4;
    yTicks.push({ v, y: scaleY(v) });
  }

  // Ticks X : 5-6 niveaux, format selon amplitude
  const spanMs = stats.tMax - stats.tMin;
  const xTicks: { t: number; x: number; label: string }[] = [];
  const nX = 5;
  for (let i = 0; i <= nX; i++) {
    const t = stats.tMin + (spanMs * i) / nX;
    const d = new Date(t);
    let label: string;
    if (spanMs < 3600 * 1000 * 2) {
      // < 2h : HH:mm:ss
      label = d.toLocaleTimeString('fr-CH', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } else if (spanMs < 24 * 3600 * 1000) {
      // < 24h : HH:mm
      label = d.toLocaleTimeString('fr-CH', { hour: '2-digit', minute: '2-digit' });
    } else if (spanMs < 7 * 24 * 3600 * 1000) {
      // < 7j : dd MMM HH:mm
      label = d.toLocaleString('fr-CH', {
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
      });
    } else {
      // > 7j : dd MMM
      label = d.toLocaleDateString('fr-CH', { day: '2-digit', month: 'short' });
    }
    xTicks.push({ t, x: scaleX(new Date(t).toISOString()), label });
  }

  // Gestion du survol : trouver le point le plus proche
  const onMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    if (mx < PADDING.left || mx > PADDING.left + innerW) {
      setHoverIdx(null);
      return;
    }
    let bestIdx = -1;
    let bestDist = Infinity;
    for (let i = 0; i < validPoints.length; i++) {
      const x = scaleX(validPoints[i].ts);
      const d = Math.abs(x - mx);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
      }
    }
    setHoverIdx(bestIdx >= 0 ? bestIdx : null);
  };

  const hover = hoverIdx !== null ? validPoints[hoverIdx] : null;
  const hoverX = hover ? scaleX(hover.ts) : 0;
  const hoverY = hover ? scaleY(hover.value!) : 0;

  return (
    <div className="relative w-full">
      <svg
        ref={svgRef}
        width={width}
        height={height}
        onMouseMove={onMouseMove}
        onMouseLeave={() => setHoverIdx(null)}
        className="block"
      >
        {/* Grille Y */}
        {yTicks.map((t, i) => (
          <g key={`yt-${i}`}>
            <line
              x1={PADDING.left}
              x2={PADDING.left + innerW}
              y1={t.y}
              y2={t.y}
              stroke="currentColor"
              strokeOpacity="0.1"
              strokeDasharray={i === 0 || i === yTicks.length - 1 ? '' : '2,3'}
            />
            <text
              x={PADDING.left - 6}
              y={t.y}
              textAnchor="end"
              dominantBaseline="middle"
              className="fill-current text-[10px] opacity-60"
            >
              {t.v.toFixed(Math.abs(stats.maxV - stats.minV) < 10 ? 1 : 0)}
            </text>
          </g>
        ))}

        {/* Ticks X */}
        {xTicks.map((t, i) => (
          <g key={`xt-${i}`}>
            <line
              x1={t.x}
              x2={t.x}
              y1={PADDING.top}
              y2={PADDING.top + innerH}
              stroke="currentColor"
              strokeOpacity="0.05"
            />
            <text
              x={t.x}
              y={PADDING.top + innerH + 16}
              textAnchor="middle"
              className="fill-current text-[10px] opacity-60"
            >
              {t.label}
            </text>
          </g>
        ))}

        {/* Ligne */}
        <path d={linePath} fill="none" stroke={color} strokeWidth="1.5" />

        {/* Points (seulement si peu nombreux) */}
        {validPoints.length <= 80 && validPoints.map((p, i) => (
          <circle
            key={`p-${i}`}
            cx={scaleX(p.ts)}
            cy={scaleY(p.value!)}
            r={CIRCLE_R}
            fill={color}
          />
        ))}

        {/* Curseur de survol */}
        {hover && (
          <g pointerEvents="none">
            <line
              x1={hoverX}
              x2={hoverX}
              y1={PADDING.top}
              y2={PADDING.top + innerH}
              stroke="currentColor"
              strokeOpacity="0.3"
              strokeDasharray="3,3"
            />
            <circle cx={hoverX} cy={hoverY} r={5} fill={color} stroke="white" strokeWidth="2" />
          </g>
        )}
      </svg>

      {/* Tooltip */}
      {hover && (
        <div
          className="pointer-events-none absolute rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-popover)] px-2 py-1 text-xs shadow-md"
          style={{
            left: Math.min(hoverX + 12, width - 140),
            top: Math.max(hoverY - 40, 4),
          }}
        >
          <div className="font-mono text-[10px] text-[color:var(--color-muted-foreground)]">
            {new Date(hover.ts).toLocaleString('fr-CH')}
          </div>
          <div className="font-semibold">
            {hover.value!.toFixed(2)}
            {unit && <span className="ml-1 font-normal text-[color:var(--color-muted-foreground)]">{unit}</span>}
          </div>
          {hover.count > 1 && (
            <div className="text-[10px] text-[color:var(--color-muted-foreground)]">
              (moyenne de {hover.count} trames)
            </div>
          )}
        </div>
      )}
    </div>
  );
}
