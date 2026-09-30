import { createFileRoute, Link } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Activity, AlertTriangle, ArrowRight, CircleGauge, Radiation, Zap } from 'lucide-react';
import { PageHeader } from '@/components/app-shell';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { StackedBars } from '@/components/dashboard/stacked-bars';
import { Donut } from '@/components/dashboard/donut';
import { HorizontalBars } from '@/components/dashboard/horizontal-bars';
import { formatNumber } from '@/lib/utils';

export const Route = createFileRoute('/')({
  component: Overview,
});

async function fetchJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

interface Summary {
  packets_per_second: number;
  frames_today: number;
  active_gateways: number;
  packet_loss_percent: number;
  protocols: Array<{ name: string; count: number; percent: number }>;
  frames_by_hour_24h: Array<{ hour: string; knx: number; bacnet: number }>;
  top_operations: Array<{ protocol: string; operation: string; count: number }>;
  errors_24h: { knx: number; bacnet: number };
  devices: { knx_gateways: number; bacnet_devices: number; bacnet_objects: number };
}

function Overview() {
  const summary = useQuery({
    queryKey: ['summary'],
    queryFn: () => fetchJson<Summary>('/api/summary'),
    refetchInterval: 10_000,
  });

  const s = summary.data;
  const totalErrors = (s?.errors_24h.knx ?? 0) + (s?.errors_24h.bacnet ?? 0);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Vue d'ensemble"
        subtitle="Capture live sur les bus techniques — auto-refresh 10s"
      />

      {/* 4 KPI cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Card>
          <CardContent className="pt-5">
            <div className="flex items-center gap-3">
              <div className="grid size-10 place-items-center rounded-md bg-[#0ea5e9]/10 text-[#0ea5e9]">
                <Activity className="size-5" />
              </div>
              <div>
                <div className="text-2xl font-bold">{formatNumber(s?.frames_today ?? 0)}</div>
                <div className="text-xs text-[color:var(--color-muted-foreground)]">Trames aujourd'hui</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <div className="flex items-center gap-3">
              <div className="grid size-10 place-items-center rounded-md bg-[#10b981]/10 text-[#10b981]">
                <Zap className="size-5" />
              </div>
              <div>
                <div className="text-2xl font-bold">{s?.packets_per_second?.toFixed(1) ?? '—'}</div>
                <div className="text-xs text-[color:var(--color-muted-foreground)]">Trames / seconde</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <div className="flex items-center gap-3">
              <div className="grid size-10 place-items-center rounded-md bg-[#f59e0b]/10 text-[#f59e0b]">
                <CircleGauge className="size-5" />
              </div>
              <div>
                <div className="text-2xl font-bold">
                  {(s?.devices.knx_gateways ?? 0) + (s?.devices.bacnet_devices ?? 0)}
                </div>
                <div className="text-xs text-[color:var(--color-muted-foreground)]">
                  Devices actifs ({s?.devices.knx_gateways ?? 0} KNX + {s?.devices.bacnet_devices ?? 0} BACnet)
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5">
            <div className="flex items-center gap-3">
              <div className={`grid size-10 place-items-center rounded-md ${totalErrors > 0 ? 'bg-red-500/10 text-red-500' : 'bg-[color:var(--color-muted)] text-[color:var(--color-muted-foreground)]'}`}>
                <AlertTriangle className="size-5" />
              </div>
              <div>
                <div className="text-2xl font-bold">{formatNumber(totalErrors)}</div>
                <div className="text-xs text-[color:var(--color-muted-foreground)]">Erreurs 24h</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Trafic par heure (grand graphique) */}
      <Card>
        <CardHeader>
          <CardTitle>Trafic des 24 dernières heures</CardTitle>
        </CardHeader>
        <CardContent>
          {s && s.frames_by_hour_24h.length > 0 ? (
            <StackedBars data={s.frames_by_hour_24h} height={260} />
          ) : (
            <div className="py-16 text-center text-sm text-[color:var(--color-muted-foreground)]">
              Chargement...
            </div>
          )}
        </CardContent>
      </Card>

      {/* Répartition + Top ops */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Répartition par protocole (aujourd'hui)</CardTitle>
          </CardHeader>
          <CardContent>
            {s && s.protocols.length > 0 ? (
              <Donut data={s.protocols} />
            ) : (
              <div className="py-8 text-center text-sm text-[color:var(--color-muted-foreground)]">Aucune donnée</div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Top opérations (24h)</CardTitle>
          </CardHeader>
          <CardContent>
            {s && s.top_operations.length > 0 ? (
              <HorizontalBars data={s.top_operations} max={8} />
            ) : (
              <div className="py-8 text-center text-sm text-[color:var(--color-muted-foreground)]">Aucune donnée</div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 2 cards nav */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="grid size-10 place-items-center rounded-md bg-[#0ea5e9]/10 text-[#0ea5e9]">
                <Radiation className="size-5" />
              </div>
              <CardTitle>KNX</CardTitle>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link to="/knx-monitor" search={{ tab: 'frames' }}>
                Ouvrir <ArrowRight className="size-4" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-3xl font-bold">{formatNumber(s?.devices.knx_gateways ?? 0)}</div>
                <div className="text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">Gateways</div>
              </div>
              <div>
                <div className="text-3xl font-bold">{formatNumber(s?.active_gateways ?? 0)}</div>
                <div className="text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">En ligne</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="grid size-10 place-items-center rounded-md bg-[#f59e0b]/10 text-[#f59e0b]">
                <Radiation className="size-5" />
              </div>
              <CardTitle>BACnet</CardTitle>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link to="/bacnet-monitor" search={{ tab: 'frames' }}>
                Ouvrir <ArrowRight className="size-4" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-3xl font-bold">{formatNumber(s?.devices.bacnet_devices ?? 0)}</div>
                <div className="text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">Devices</div>
              </div>
              <div>
                <div className="text-3xl font-bold">{formatNumber(s?.devices.bacnet_objects ?? 0)}</div>
                <div className="text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">Objets</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
