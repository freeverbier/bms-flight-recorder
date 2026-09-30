import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, RefreshCw, Search, Trash2, Zap } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/primitives';
import { api } from '@/lib/api';
import type { BacnetDevice } from '@/lib/types';

interface Props {
  onSelectDevice?: (id: string) => void;
  selectedDeviceId?: string;
}

export function DeviceTable({ onSelectDevice, selectedDeviceId }: Props) {
  const queryClient = useQueryClient();
  const [showManual, setShowManual] = useState(false);
  const [manualIp, setManualIp] = useState('');
  const [manualPort, setManualPort] = useState('47808');
  const [manualName, setManualName] = useState('');

  const devices = useQuery({
    queryKey: ['bacnet-devices'],
    queryFn: () => api.bacnetDevices(),
    refetchInterval: 10_000,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['bacnet-devices'] });

  const discoverMutation = useMutation({
    mutationFn: () => api.bacnetDiscover({ target: '255.255.255.255', port: 47808 }),
    onSuccess: () => {
      toast.success('WhoIs envoyé — les devices vont apparaître sous quelques secondes');
      setTimeout(invalidate, 3000);
    },
    onError: (e: Error) => toast.error(`Erreur : ${e.message}`),
  });

  const addManualMutation = useMutation({
    mutationFn: () =>
      api.bacnetCreateDevice({
        ip_address: manualIp,
        port: parseInt(manualPort, 10) || 47808,
        name: manualName || undefined,
      }),
    onSuccess: () => {
      toast.success('Device ajouté');
      setManualIp('');
      setManualName('');
      setShowManual(false);
      invalidate();
    },
    onError: (e: Error) => toast.error(`Erreur : ${e.message}`),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.bacnetDeleteDevice(id),
    onSuccess: () => {
      toast.success('Device supprimé');
      invalidate();
    },
    onError: (e: Error) => toast.error(`Erreur : ${e.message}`),
  });

  const rows = devices.data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="default"
          onClick={() => discoverMutation.mutate()}
          disabled={discoverMutation.isPending}
        >
          <Zap />
          {discoverMutation.isPending ? 'Envoi…' : 'Envoyer un Who-Is'}
        </Button>
        <Button size="sm" variant="outline" onClick={() => setShowManual((s) => !s)}>
          <Plus />
          Ajouter manuellement
        </Button>
        <Button size="sm" variant="ghost" onClick={() => devices.refetch()}>
          <RefreshCw />
        </Button>
        <div className="ml-auto text-xs text-[color:var(--color-muted-foreground)]">
          {rows.length} device(s) détecté(s)
        </div>
      </div>

      {showManual && (
        <div className="grid gap-2 rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-muted)]/30 p-3 md:grid-cols-[1fr_100px_1fr_auto]">
          <div>
            <Label htmlFor="add-ip">IP</Label>
            <Input id="add-ip" placeholder="192.168.0.84" value={manualIp} onChange={(e) => setManualIp(e.target.value)} />
          </div>
          <div>
            <Label htmlFor="add-port">Port</Label>
            <Input id="add-port" placeholder="47808" value={manualPort} onChange={(e) => setManualPort(e.target.value)} />
          </div>
          <div>
            <Label htmlFor="add-name">Nom</Label>
            <Input id="add-name" placeholder="Thermostat simu" value={manualName} onChange={(e) => setManualName(e.target.value)} />
          </div>
          <div className="flex items-end">
            <Button size="sm" onClick={() => addManualMutation.mutate()} disabled={!manualIp || addManualMutation.isPending}>
              Ajouter
            </Button>
          </div>
        </div>
      )}

      <div className="overflow-x-auto rounded-md border border-[color:var(--color-border)]">
        <table className="w-full text-sm">
          <thead className="bg-[color:var(--color-muted)] text-left text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">
            <tr>
              <th className="px-3 py-2">Adresse</th>
              <th className="px-3 py-2">Device ID</th>
              <th className="px-3 py-2">Vendor</th>
              <th className="px-3 py-2">Max APDU</th>
              <th className="px-3 py-2">Segmentation</th>
              <th className="px-3 py-2">Objets</th>
              <th className="px-3 py-2">Vu</th>
              <th className="px-3 py-2 w-16"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr
                key={d.id}
                className={`cursor-pointer border-t border-[color:var(--color-border)] hover:bg-[color:var(--color-muted)]/40 ${
                  selectedDeviceId === d.id ? 'bg-[color:var(--color-muted)]/60' : ''
                }`}
                onClick={() => onSelectDevice?.(d.id)}
              >
                <td className="px-3 py-2 font-mono text-xs">
                  {d.ip_address}:{d.port}
                  {d.name && <div className="text-[10px] text-[color:var(--color-muted-foreground)]">{d.name}</div>}
                </td>
                <td className="px-3 py-2 font-mono text-xs">{d.device_id ?? '—'}</td>
                <td className="px-3 py-2 text-xs">{d.vendor_id ?? '—'}</td>
                <td className="px-3 py-2 text-xs">{d.max_apdu ?? '—'}</td>
                <td className="px-3 py-2 text-xs">{d.segmentation ?? '—'}</td>
                <td className="px-3 py-2">
                  {d.n_objects > 0 ? (
                    <Badge variant="outline" className="text-[10px]">
                      <Search className="mr-1 size-3" />
                      {d.n_objects}
                    </Badge>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-[color:var(--color-muted-foreground)]">
                  {new Date(d.last_seen).toLocaleTimeString()}
                </td>
                <td className="px-3 py-2 text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="size-7 p-0"
                    title="Supprimer"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (window.confirm(`Supprimer ${d.ip_address}:${d.port} et ses objets ?`)) {
                        deleteMutation.mutate(d.id);
                      }
                    }}
                  >
                    <Trash2 className="size-3.5 text-red-600" />
                  </Button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
                  Aucun device détecté. Clique sur « Envoyer un Who-Is » ou attends que du trafic BACnet transite.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
