import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, LineChart as LineChartIcon, Pencil, RotateCcw, X } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import type { BacnetObject } from '@/lib/types';

interface Props {
  deviceId?: string;
  onShowHistory?: (addressAndField: string) => void;
}

export function ObjectTable({ deviceId, onShowHistory }: Props) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<BacnetObject>>({});

  const objects = useQuery({
    queryKey: ['bacnet-objects', deviceId, search],
    queryFn: () => api.bacnetObjects({ device_id: deviceId, search }),
    refetchInterval: 15_000,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['bacnet-objects'] });

  const updateMutation = useMutation({
    mutationFn: (v: { id: string; patch: Partial<BacnetObject> }) => api.bacnetUpdateObject(v.id, v.patch),
    onSuccess: () => {
      toast.success('Objet mis à jour');
      setEditing(null);
      setDraft({});
      invalidate();
    },
    onError: (e: Error) => toast.error(`Erreur : ${e.message}`),
  });

  const resetMutation = useMutation({
    mutationFn: (id: string) => api.bacnetResetObject(id),
    onSuccess: () => {
      toast.success('Restauré depuis auto-découvert');
      invalidate();
    },
    onError: (e: Error) => toast.error(`Erreur : ${e.message}`),
  });

  const startEdit = (o: BacnetObject) => {
    setEditing(o.id);
    setDraft({ name: o.name || '', unit: o.unit || '', description: o.description || '' });
  };

  const commitEdit = (id: string) => {
    const patch: Partial<BacnetObject> = {};
    if (draft.name !== undefined) patch.name = draft.name;
    if (draft.unit !== undefined) patch.unit = draft.unit;
    if (draft.description !== undefined) patch.description = draft.description;
    updateMutation.mutate({ id, patch });
  };

  const rows = objects.data ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Input
          placeholder="Filtrer par object-ref ou nom"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        <div className="ml-auto text-xs text-[color:var(--color-muted-foreground)]">
          {rows.length} objet(s){deviceId && ' pour ce device'}
        </div>
      </div>

      <div className="max-h-[500px] overflow-y-auto rounded-md border border-[color:var(--color-border)]">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-[color:var(--color-muted)] text-left text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">
            <tr>
              <th className="px-3 py-2">Device</th>
              <th className="px-3 py-2">Object</th>
              <th className="px-3 py-2">Nom</th>
              <th className="px-3 py-2">Unité</th>
              <th className="px-3 py-2">Description</th>
              <th className="px-3 py-2">Statut</th>
              <th className="px-3 py-2 w-28 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => {
              const isEdit = editing === o.id;
              return (
                <tr key={o.id} className={`border-t border-[color:var(--color-border)] ${isEdit ? 'bg-[color:var(--color-muted)]/40' : ''}`}>
                  <td className="px-3 py-2 font-mono text-xs">
                    {o.device_ip}:{o.device_port}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{o.object_ref}</td>
                  <td className="px-3 py-2">
                    {isEdit ? (
                      <Input
                        value={draft.name || ''}
                        onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                        className="h-8 text-xs"
                      />
                    ) : (
                      <>
                        <div>{o.name || '—'}</div>
                        {o.is_modified && o.name_imported && o.name_imported !== o.name && (
                          <div className="text-[10px] text-[color:var(--color-muted-foreground)] line-through">
                            auto: {o.name_imported}
                          </div>
                        )}
                      </>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {isEdit ? (
                      <Input
                        value={draft.unit || ''}
                        onChange={(e) => setDraft({ ...draft, unit: e.target.value })}
                        className="h-8 text-xs"
                        placeholder="°C, %, kWh…"
                      />
                    ) : (
                      <div className="text-xs">{o.unit || '—'}</div>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {isEdit ? (
                      <Input
                        value={draft.description || ''}
                        onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                        className="h-8 text-xs"
                      />
                    ) : (
                      <div className="text-xs text-[color:var(--color-muted-foreground)]">{o.description || '—'}</div>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {o.is_modified ? (
                      <Badge variant="warning" className="text-[10px]">
                        <Pencil className="mr-1 size-3" />manuel
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-[10px]">auto</Badge>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {isEdit ? (
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" className="size-7 p-0" onClick={() => commitEdit(o.id)} disabled={updateMutation.isPending}>
                          <Check className="text-green-600" />
                        </Button>
                        <Button size="sm" variant="ghost" className="size-7 p-0" onClick={() => { setEditing(null); setDraft({}); }}>
                          <X />
                        </Button>
                      </div>
                    ) : (
                      <div className="flex justify-end gap-1">
                        {onShowHistory && (
                          <Button size="sm" variant="ghost" className="size-7 p-0" title="Historique"
                            onClick={() => onShowHistory(`${o.object_ref}|value_num`)}>
                            <LineChartIcon className="size-3.5" />
                          </Button>
                        )}
                        <Button size="sm" variant="ghost" className="size-7 p-0" title="Éditer" onClick={() => startEdit(o)}>
                          <Pencil className="size-3.5" />
                        </Button>
                        {o.is_modified && (
                          <Button size="sm" variant="ghost" className="size-7 p-0" title="Restaurer auto-découvert"
                            onClick={() => {
                              if (window.confirm(`Restaurer les valeurs auto-découvertes pour ${o.object_ref} ?`)) {
                                resetMutation.mutate(o.id);
                              }
                            }}>
                            <RotateCcw className="size-3.5 text-blue-600" />
                          </Button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
                  {deviceId
                    ? "Ce device n'a pas encore d'objets connus. Interroge une propriété depuis Yabe pour peupler la liste."
                    : "Aucun objet détecté. Utilise Yabe pour interroger des propriétés — les objets apparaîtront ici."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
