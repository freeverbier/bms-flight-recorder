import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Radar, Radio, RefreshCw, Search, Trash2, Wifi } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/primitives';
import { api } from '@/lib/api';
import { formatDateTime } from '@/lib/utils';
import type { BacnetScan, BacnetDevice } from '@/lib/types';

const statusVariant: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  queued: 'outline',
  running: 'default',
  completed: 'secondary',
  failed: 'destructive',
};

export function ScanPanel() {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState('');

  // Auto-refresh + polling accéléré si un scan est en cours
  const scans = useQuery({
    queryKey: ['bacnet-scans'],
    queryFn: api.bacnetScans,
    refetchInterval: (query) => {
      const rows = (query.state.data ?? []) as BacnetScan[];
      return rows.some((s) => s.status === 'running' || s.status === 'queued') ? 1500 : 5000;
    },
  });

  const devices = useQuery({
    queryKey: ['bacnet-devices'],
    queryFn: api.bacnetDevices,
    refetchInterval: 5000,
  });

  const discover = useMutation({
    mutationFn: () => api.bacnetDiscover({ target: target || undefined }),
    onSuccess: (data) => {
      toast.success(`Who-Is lancé (job ${data.job_id.slice(0, 8)})`);
      queryClient.invalidateQueries({ queryKey: ['bacnet-scans'] });
    },
    onError: (err: Error) => toast.error(`Erreur : ${err.message}`),
  });

  const discoverObjects = useMutation({
    mutationFn: (deviceUuid: string) => api.bacnetDiscoverObjects(deviceUuid),
    onSuccess: () => {
      toast.success('Découverte des objets lancée');
      queryClient.invalidateQueries({ queryKey: ['bacnet-scans'] });
    },
    onError: (err: Error) => toast.error(`Erreur : ${err.message}`),
  });

  const deleteDevice = useMutation({
    mutationFn: (id: string) => api.bacnetDeleteDevice(id),
    onSuccess: () => {
      toast.success('Device supprimé');
      queryClient.invalidateQueries({ queryKey: ['bacnet-devices'] });
    },
    onError: (err: Error) => toast.error(`Erreur : ${err.message}`),
  });

  return (
    <div className="flex flex-col gap-4">
      {/* Card 1 : Lancer un Who-Is */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-md bg-[#f59e0b]/10 text-[#f59e0b]">
              <Radar className="size-5" />
            </div>
            <div>
              <CardTitle>Découverte BACnet — Who-Is</CardTitle>
              <CardDescription>
                Envoie un broadcast Who-Is sur le sous-réseau ; les I-Am renvoyés peuplent la liste des devices.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-3 md:flex-row md:items-end">
            <div className="flex-1">
              <Label htmlFor="whois-target">Cible (optionnel)</Label>
              <Input
                id="whois-target"
                placeholder="192.168.0.255 (broadcast local par défaut)"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              />
            </div>
            <Button
              onClick={() => discover.mutate()}
              disabled={discover.isPending}
              className="md:w-48"
            >
              <Radio className="mr-2 size-4" />
              {discover.isPending ? 'Envoi…' : 'Lancer un Who-Is'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Card 2 : Scans récents */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Scans récents</CardTitle>
            <CardDescription>
              Historique des jobs de découverte (auto-refresh)
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => scans.refetch()}
            disabled={scans.isFetching}
          >
            <RefreshCw className={`size-4 ${scans.isFetching ? 'animate-spin' : ''}`} />
          </Button>
        </CardHeader>
        <CardContent>
          {(scans.data ?? []).length === 0 ? (
            <div className="py-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
              Aucun scan lancé. Utilise le bouton ci-dessus pour commencer.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-[color:var(--color-muted-foreground)]">
                  <tr className="border-b border-[color:var(--color-border)]">
                    <th className="py-2 text-left font-medium">Créé</th>
                    <th className="py-2 text-left font-medium">Mode</th>
                    <th className="py-2 text-left font-medium">Cible</th>
                    <th className="py-2 text-left font-medium">Statut</th>
                    <th className="py-2 text-left font-medium">Durée</th>
                  </tr>
                </thead>
                <tbody>
                  {(scans.data ?? []).map((s) => (
                    <tr key={s.id} className="border-b border-[color:var(--color-border)]/50">
                      <td className="py-2 font-mono text-xs">{formatDateTime(s.created_at)}</td>
                      <td className="py-2 text-xs">{s.mode}</td>
                      <td className="py-2 font-mono text-xs">{s.target}</td>
                      <td className="py-2">
                        <Badge variant={statusVariant[s.status] || 'outline'}>{s.status}</Badge>
                      </td>
                      <td className="py-2 text-xs text-[color:var(--color-muted-foreground)]">
                        {computeDuration(s.started_at, s.completed_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Card 3 : Devices détectés */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Devices BACnet détectés</CardTitle>
            <CardDescription>
              Devices vus depuis le démarrage du sniffer
            </CardDescription>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => devices.refetch()}
            disabled={devices.isFetching}
          >
            <RefreshCw className={`size-4 ${devices.isFetching ? 'animate-spin' : ''}`} />
          </Button>
        </CardHeader>
        <CardContent>
          {(devices.data ?? []).length === 0 ? (
            <div className="py-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
              Aucun device détecté. Lance un Who-Is pour découvrir des équipements.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase text-[color:var(--color-muted-foreground)]">
                  <tr className="border-b border-[color:var(--color-border)]">
                    <th className="py-2 text-left font-medium">IP</th>
                    <th className="py-2 text-left font-medium">Device ID</th>
                    <th className="py-2 text-left font-medium">Vendor</th>
                    <th className="py-2 text-left font-medium">Objets</th>
                    <th className="py-2 text-left font-medium">Vu</th>
                    <th className="py-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(devices.data ?? []).map((d: BacnetDevice) => {
                    const isSelf = d.ip_address === '192.168.0.147';
                    return (
                      <tr key={d.id} className="border-b border-[color:var(--color-border)]/50">
                        <td className="py-2 font-mono text-xs">
                          {d.ip_address}:{d.port}
                          {isSelf && (
                            <Badge variant="outline" className="ml-2 text-[10px]">
                              nous
                            </Badge>
                          )}
                        </td>
                        <td className="py-2 text-xs">
                          {d.device_id ?? <span className="text-[color:var(--color-muted-foreground)]">—</span>}
                        </td>
                        <td className="py-2 text-xs">
                          {d.vendor_id ?? <span className="text-[color:var(--color-muted-foreground)]">—</span>}
                        </td>
                        <td className="py-2 text-xs">
                          <Badge variant="secondary">{d.n_objects ?? 0}</Badge>
                        </td>
                        <td className="py-2 text-xs text-[color:var(--color-muted-foreground)]">
                          {formatRelative(d.last_seen)}
                        </td>
                        <td className="py-2 text-right">
                          <div className="flex justify-end gap-1">
                            {!isSelf && d.device_id != null && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => discoverObjects.mutate(d.id)}
                                disabled={discoverObjects.isPending}
                                title="Découvrir les objets"
                              >
                                <Search className="size-3.5" />
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => {
                                if (confirm(`Supprimer ${d.ip_address}:${d.port} ?`)) {
                                  deleteDevice.mutate(d.id);
                                }
                              }}
                              disabled={deleteDevice.isPending}
                              title="Supprimer"
                            >
                              <Trash2 className="size-3.5" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function computeDuration(started: string | null, completed: string | null): string {
  if (!started) return '—';
  const start = new Date(started).getTime();
  const end = completed ? new Date(completed).getTime() : Date.now();
  const ms = end - start;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1000)}s`;
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const secs = Math.floor((now - then) / 1000);
  if (secs < 10) return "à l'instant";
  if (secs < 60) return `il y a ${secs}s`;
  if (secs < 3600) return `il y a ${Math.floor(secs / 60)}min`;
  if (secs < 86400) return `il y a ${Math.floor(secs / 3600)}h`;
  return new Date(iso).toLocaleDateString('fr-FR');
}
