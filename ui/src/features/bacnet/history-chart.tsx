import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/primitives';
import { api } from '@/lib/api';

export type HistoryRange = '1h' | '6h' | '24h' | '7d' | '30d';

const RANGES: { value: HistoryRange; label: string }[] = [
  { value: '1h', label: '1 h' },
  { value: '6h', label: '6 h' },
  { value: '24h', label: '24 h' },
  { value: '7d', label: '7 j' },
  { value: '30d', label: '30 j' },
];

interface Props {
  initialAddress?: string;
  initialField?: string;
  initialRange?: HistoryRange;
  onAddressChange?: (v: string) => void;
  onFieldChange?: (v: string) => void;
  onRangeChange?: (v: HistoryRange) => void;
}

export function HistoryTab({
  initialAddress = '',
  initialField = 'value_num',
  initialRange = '24h',
  onAddressChange,
  onFieldChange,
  onRangeChange,
}: Props) {
  const [address, setAddress] = useState(initialAddress);
  const [field, setField] = useState(initialField);
  const [range, setRange] = useState<HistoryRange>(initialRange);

  const query = useQuery({
    queryKey: ['bacnet-history', address, field, range],
    queryFn: () => api.bacnetHistory(address, range, field),
    enabled: !!address,
    staleTime: 15_000,
  });

  const points = query.data?.points ?? [];
  const stats = useMemo(() => {
    if (!points.length) return null;
    const values = points.map((p) => p.value).filter((v): v is number => v !== null);
    if (!values.length) return null;
    return {
      count: values.length,
      min: Math.min(...values),
      max: Math.max(...values),
      avg: values.reduce((a, b) => a + b, 0) / values.length,
      last: values[values.length - 1],
    };
  }, [points]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Historique BACnet</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto_auto]">
          <div>
            <Label htmlFor="hist-addr">Object ref</Label>
            <Input
              id="hist-addr"
              placeholder="analog-input:5"
              value={address}
              onChange={(e) => {
                setAddress(e.target.value);
                onAddressChange?.(e.target.value);
              }}
            />
          </div>
          <div>
            <Label htmlFor="hist-field">Champ</Label>
            <Input
              id="hist-field"
              placeholder="value_num"
              value={field}
              onChange={(e) => {
                setField(e.target.value);
                onFieldChange?.(e.target.value);
              }}
            />
          </div>
          <div>
            <Label>Période</Label>
            <div className="flex gap-1">
              {RANGES.map((r) => (
                <Button
                  key={r.value}
                  size="sm"
                  variant={range === r.value ? 'default' : 'outline'}
                  onClick={() => {
                    setRange(r.value);
                    onRangeChange?.(r.value);
                  }}
                >
                  {r.label}
                </Button>
              ))}
            </div>
          </div>
          <div className="flex items-end">
            <Button size="sm" variant="outline" onClick={() => query.refetch()} disabled={!address}>
              <RefreshCw />
            </Button>
          </div>
        </div>

        {query.isError && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900">
            Erreur : {(query.error as Error).message}
          </div>
        )}

        {!address ? (
          <div className="rounded-md border border-dashed border-[color:var(--color-border)] p-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
            Entre un object-ref (ex. <code>analog-input:5</code>) pour afficher son historique.
          </div>
        ) : query.isLoading ? (
          <div className="p-8 text-center text-sm">Chargement…</div>
        ) : points.length === 0 ? (
          <div className="rounded-md border border-dashed border-[color:var(--color-border)] p-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
            Aucune donnée sur la période sélectionnée.
          </div>
        ) : (
          <>
            {stats && (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                <StatCard label="Points" value={stats.count.toString()} />
                <StatCard label="Min" value={stats.min.toFixed(2)} />
                <StatCard label="Moy" value={stats.avg.toFixed(2)} />
                <StatCard label="Max" value={stats.max.toFixed(2)} />
                <StatCard label="Dernière" value={stats.last.toFixed(2)} />
              </div>
            )}
            <LineChart points={points} />
          </>
        )}
      </CardContent>
    </Card>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-muted)]/30 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-[color:var(--color-muted-foreground)]">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

interface LineChartProps {
  points: { ts: string; value: number | null }[];
}

function LineChart({ points }: LineChartProps) {
  const W = 800;
  const H = 260;
  const PAD_L = 50;
  const PAD_B = 30;
  const PAD_T = 10;
  const PAD_R = 20;

  const valid = points.filter((p) => p.value !== null) as { ts: string; value: number }[];
  if (valid.length < 2) {
    return <div className="text-sm">Pas assez de données pour tracer.</div>;
  }

  const values = valid.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const t0 = new Date(valid[0].ts).getTime();
  const tN = new Date(valid[valid.length - 1].ts).getTime();
  const dt = tN - t0 || 1;

  const path = valid
    .map((p, i) => {
      const x = PAD_L + ((new Date(p.ts).getTime() - t0) / dt) * (W - PAD_L - PAD_R);
      const y = PAD_T + (1 - (p.value - min) / range) * (H - PAD_T - PAD_B);
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((t) => {
    const val = min + t * range;
    const y = PAD_T + (1 - t) * (H - PAD_T - PAD_B);
    return { y, label: val.toFixed(2) };
  });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-64 border border-[color:var(--color-border)] rounded-md bg-[color:var(--color-card)]">
      {yTicks.map((t, i) => (
        <g key={i}>
          <line x1={PAD_L} y1={t.y} x2={W - PAD_R} y2={t.y} stroke="currentColor" strokeOpacity="0.1" />
          <text x={PAD_L - 5} y={t.y + 3} textAnchor="end" fontSize="10" fill="currentColor" opacity="0.6">
            {t.label}
          </text>
        </g>
      ))}
      <path d={path} fill="none" stroke="rgb(59, 130, 246)" strokeWidth="1.5" />
    </svg>
  );
}
