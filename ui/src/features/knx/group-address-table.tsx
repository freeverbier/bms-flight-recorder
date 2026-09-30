// Round 7 — Table éditable des adresses de groupe avec override manuel.
// Permet de modifier DPT / nom / unité / description après import ETS,
// avec préservation lors du ré-import et bouton "Restaurer" pour retrouver
// la valeur d'origine.

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, LineChart as LineChartIcon, Package, Pencil, RotateCcw, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api } from '@/lib/api';
import type { DptRegistryEntry, KnxGroupAddress } from '@/lib/types';

const selectClass =
  'h-8 w-full rounded-md border border-[color:var(--color-input)] bg-transparent px-2 text-xs shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color:var(--color-ring)]';

interface Props {
  search: string;
  onShowHistory?: (address: string) => void;
}

export function GroupAddressTable({ search, onShowHistory }: Props) {
  const queryClient = useQueryClient();

  const groups = useQuery({
    queryKey: ['knx-groups', search],
    queryFn: () => api.knxGroupAddresses(search || undefined),
  });

  const registry = useQuery({
    queryKey: ['dpt-registry-enabled'],
    queryFn: () => api.dptRegistry(false),
    staleTime: 60_000,
  });

  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<KnxGroupAddress>>({});

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['knx-groups'] });

  const updateMutation = useMutation({
    mutationFn: (payload: { address: string; patch: Partial<KnxGroupAddress> }) =>
      api.updateKnxGroupAddress(payload.address, payload.patch),
    onSuccess: () => {
      toast.success('Sémantique mise à jour');
      setEditing(null);
      setDraft({});
      invalidate();
    },
    onError: (e: Error) => toast.error(`Erreur : ${e.message}`),
  });

  const resetMutation = useMutation({
    mutationFn: (address: string) => api.resetKnxGroupAddress(address),
    onSuccess: () => {
      toast.success("Restauré depuis l'import ETS");
      invalidate();
    },
    onError: (e: Error) => toast.error(`Erreur : ${e.message}`),
  });

  const deleteMutation = useMutation({
    mutationFn: (address: string) => api.deleteKnxGroupAddress(address),
    onSuccess: () => {
      toast.success('Adresse supprimée');
      invalidate();
    },
    onError: (e: Error) => toast.error(`Erreur : ${e.message}`),
  });

  const dptOptions = useMemo(() => {
    const list = (registry.data ?? []) as DptRegistryEntry[];
    return list.map((d) => ({
      value: d.dpt_id,
      label: `${d.dpt_id} — ${d.name}${d.unit ? ` (${d.unit})` : ''}`,
      unit: d.unit,
    }));
  }, [registry.data]);

  const startEdit = (row: KnxGroupAddress) => {
    setEditing(row.address);
    setDraft({
      name: row.name,
      dpt: row.dpt || '',
      unit: row.unit || '',
      description: row.description || '',
    });
  };

  const cancelEdit = () => {
    setEditing(null);
    setDraft({});
  };

  const commitEdit = (address: string) => {
    const patch: Partial<KnxGroupAddress> = {};
    if (draft.name !== undefined) patch.name = draft.name;
    if (draft.dpt !== undefined) patch.dpt = draft.dpt || null;
    if (draft.unit !== undefined) patch.unit = draft.unit || null;
    if (draft.description !== undefined) patch.description = draft.description || null;
    updateMutation.mutate({ address, patch });
  };

  const rows = groups.data ?? [];

  return (
    <div className="max-h-[640px] overflow-y-auto rounded-md border border-[color:var(--color-border)]">
      <table className="w-full text-sm">
        <thead className="sticky top-0 z-10 bg-[color:var(--color-muted)] text-left text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">
          <tr>
            <th className="px-3 py-2">Adresse</th>
            <th className="px-3 py-2">Nom</th>
            <th className="px-3 py-2">DPT</th>
            <th className="px-3 py-2">Unité</th>
            <th className="px-3 py-2">Description</th>
            <th className="px-3 py-2">Source</th>
            <th className="px-3 py-2 w-32 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((g) => {
            const isEdit = editing === g.address;
            const importDiffers =
              g.is_modified && g.has_import && (
                (g.dpt || '') !== (g.dpt_imported || '')
                || (g.name || '') !== (g.name_imported || '')
                || (g.unit || '') !== (g.unit_imported || '')
                || (g.description || '') !== (g.description_imported || '')
              );
            return (
              <tr
                key={g.address}
                className={`border-t border-[color:var(--color-border)] ${isEdit ? 'bg-[color:var(--color-muted)]/40' : ''}`}
              >
                <td className="px-3 py-2 font-mono text-xs">{g.address}</td>

                {/* Nom */}
                <td className="px-3 py-2">
                  {isEdit ? (
                    <Input
                      value={draft.name || ''}
                      onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                      className="h-8 text-xs"
                    />
                  ) : (
                    <>
                      <div>{g.name}</div>
                      {importDiffers && g.name !== g.name_imported && (
                        <div className="text-[10px] text-[color:var(--color-muted-foreground)] line-through">
                          import: {g.name_imported}
                        </div>
                      )}
                    </>
                  )}
                </td>

                {/* DPT — dropdown depuis registry */}
                <td className="px-3 py-2">
                  {isEdit ? (
                    <select
                      value={draft.dpt || ''}
                      onChange={(e) => {
                        const opt = dptOptions.find((o) => o.value === e.target.value);
                        setDraft({
                          ...draft,
                          dpt: e.target.value,
                          // Auto-remplit unité si vide
                          unit: draft.unit || opt?.unit || '',
                        });
                      }}
                      className={selectClass}
                    >
                      <option value="">— aucun —</option>
                      {dptOptions.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  ) : (
                    <>
                      <div className="font-mono text-xs">{g.dpt || '—'}</div>
                      {importDiffers && (g.dpt || '') !== (g.dpt_imported || '') && (
                        <div className="text-[10px] text-[color:var(--color-muted-foreground)] line-through">
                          import: {g.dpt_imported || '—'}
                        </div>
                      )}
                    </>
                  )}
                </td>

                {/* Unité */}
                <td className="px-3 py-2">
                  {isEdit ? (
                    <Input
                      value={draft.unit || ''}
                      onChange={(e) => setDraft({ ...draft, unit: e.target.value })}
                      className="h-8 text-xs"
                      placeholder="°C, %, kWh…"
                    />
                  ) : (
                    <>
                      <div className="text-xs">{g.unit || '—'}</div>
                      {importDiffers && (g.unit || '') !== (g.unit_imported || '') && (
                        <div className="text-[10px] text-[color:var(--color-muted-foreground)] line-through">
                          import: {g.unit_imported || '—'}
                        </div>
                      )}
                    </>
                  )}
                </td>

                {/* Description */}
                <td className="px-3 py-2">
                  {isEdit ? (
                    <Input
                      value={draft.description || ''}
                      onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                      className="h-8 text-xs"
                    />
                  ) : (
                    <div className="text-xs text-[color:var(--color-muted-foreground)]">
                      {g.description || '—'}
                    </div>
                  )}
                </td>

                {/* Source */}
                <td className="px-3 py-2">
                  {g.is_modified ? (
                    <Badge variant="warning" className="text-[10px]">
                      <Pencil className="mr-1 size-3" />manuel
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-[10px]">
                      <Package className="mr-1 size-3" />
                      {g.source.replace('ets_', '')}
                    </Badge>
                  )}
                </td>

                {/* Actions */}
                <td className="px-3 py-2 text-right">
                  {isEdit ? (
                    <div className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" className="size-7 p-0"
                        onClick={() => commitEdit(g.address)}
                        disabled={updateMutation.isPending}>
                        <Check className="text-green-600" />
                      </Button>
                      <Button size="sm" variant="ghost" className="size-7 p-0" onClick={cancelEdit}>
                        <X />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex justify-end gap-1">
                      {onShowHistory && g.address.includes('/') && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="size-7 p-0"
                          title="Historique"
                          onClick={() => onShowHistory(g.address)}
                        >
                          <LineChartIcon className="size-3.5" />
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="size-7 p-0"
                        title="Éditer"
                        onClick={() => startEdit(g)}
                      >
                        <Pencil className="size-3.5" />
                      </Button>
                      {g.is_modified && g.has_import && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="size-7 p-0"
                          title="Restaurer valeur d'import ETS"
                          onClick={() => {
                            if (window.confirm(`Restaurer les valeurs d'import ETS pour ${g.address} ? Ton override manuel sera perdu.`)) {
                              resetMutation.mutate(g.address);
                            }
                          }}
                        >
                          <RotateCcw className="size-3.5 text-blue-600" />
                        </Button>
                      )}
                      {g.is_modified && !g.has_import && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="size-7 p-0"
                          title="Supprimer (créée manuellement)"
                          onClick={() => {
                            if (window.confirm(`Supprimer la GA ${g.address} ?`)) {
                              deleteMutation.mutate(g.address);
                            }
                          }}
                        >
                          <Trash2 className="size-3.5 text-red-600" />
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
                Aucune adresse trouvée. Utilise l'import ESF ou .knxproj à gauche.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
