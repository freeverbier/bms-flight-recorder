import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { AlertTriangle, Code2, Package, Pencil, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { PageHeader } from '@/components/app-shell';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/primitives';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { api } from '@/lib/api';
import type { DptRegistryEntry, DptRegistryPayload, DptKind } from '@/lib/types';

const KIND_OPTIONS: { value: DptKind; label: string; description: string }[] = [
  { value: 'bool', label: 'Booléen (1 bit)', description: 'DPT 1.xxx' },
  { value: 'uint8', label: 'uint8 (1 byte)', description: 'Counter, scaled' },
  { value: 'int8', label: 'int8 (1 byte)', description: 'Signed' },
  { value: 'percent_u8', label: '% (0..100, u8)', description: 'DPT 5.001' },
  { value: 'angle_u8', label: 'Angle (0..360°, u8)', description: 'DPT 5.003' },
  { value: 'uint16', label: 'uint16 (2 bytes)', description: 'Counter u16' },
  { value: 'int16', label: 'int16 (2 bytes)', description: 'Signed u16' },
  { value: 'float16', label: 'KNX Float16 (2 bytes)', description: 'DPT 9.xxx' },
  { value: 'uint32', label: 'uint32 (4 bytes)', description: 'Counter' },
  { value: 'int32', label: 'int32 (4 bytes)', description: 'Energy, signed' },
  { value: 'float32', label: 'IEEE Float32 (4 bytes)', description: 'DPT 14.xxx' },
  { value: 'step_control', label: 'Step control (4 bits)', description: 'DPT 3.007/3.008 dimming/blinds' },
  { value: 'time', label: 'Time of day (3 bytes)', description: 'DPT 10.001' },
  { value: 'date', label: 'Date (3 bytes)', description: 'DPT 11.001' },
  { value: 'string_ascii', label: 'String ASCII (14 bytes)', description: 'DPT 16.000' },
  { value: 'enum', label: 'Enum (u8 + mapping)', description: 'DPT 20.xxx' },
  { value: 'bitfield', label: 'Bitfield (fields nommés)', description: 'DPT 21.xxx' },
  { value: 'custom_struct', label: 'Struct custom (déclaratif)', description: 'Champs multiples' },
  { value: 'custom_handler', label: 'Handler Python', description: 'Code custom (avertissement sécurité)' },
  { value: 'bytes', label: 'Bytes bruts', description: 'Hex fallback' },
];

const selectClass =
  'mt-1 h-9 w-full rounded-md border border-[color:var(--color-input)] bg-transparent px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--color-ring)]';

export function DptRegistryPanel() {
  const registry = useQuery({
    queryKey: ['dpt-registry'],
    queryFn: () => api.dptRegistry(true),
    refetchInterval: 30_000,
  });

  const [filter, setFilter] = useState('');
  const [showStandard, setShowStandard] = useState(true);
  const [showCustom, setShowCustom] = useState(true);
  const [showDisabled, setShowDisabled] = useState(false);
  const [editing, setEditing] = useState<DptRegistryEntry | null>(null);
  const [creating, setCreating] = useState(false);

  const entries = useMemo(() => {
    const all = registry.data ?? [];
    const q = filter.trim().toLowerCase();
    return all.filter((e) => {
      if (e.is_standard && !showStandard) return false;
      if (!e.is_standard && !showCustom) return false;
      if (!e.enabled && !showDisabled) return false;
      if (!q) return true;
      return [e.dpt_id, e.name, e.description, e.unit].some((v) =>
        (v || '').toLowerCase().includes(q),
      );
    });
  }, [registry.data, filter, showStandard, showCustom, showDisabled]);

  const counts = useMemo(() => {
    const all = registry.data ?? [];
    return {
      total: all.length,
      standard: all.filter((e) => e.is_standard).length,
      custom: all.filter((e) => !e.is_standard).length,
      disabled: all.filter((e) => !e.enabled).length,
    };
  }, [registry.data]);

  return (
    <>
      <PageHeader
        title="Registre DPT"
        subtitle="Catalogue des Data Point Types utilisés pour décoder les télégrammes KNX."
        action={
          <Button onClick={() => setCreating(true)}>
            <Plus />
            Ajouter un DPT
          </Button>
        }
      />

      <Card className="mb-4">
        <CardContent className="pt-6">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <div>
              <div className="text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">Total</div>
              <div className="mt-1 text-2xl font-semibold">{counts.total}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">Standard</div>
              <div className="mt-1 text-2xl font-semibold">{counts.standard}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">Custom</div>
              <div className="mt-1 text-2xl font-semibold text-cyan-600">{counts.custom}</div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">Désactivés</div>
              <div className="mt-1 text-2xl font-semibold text-[color:var(--color-muted-foreground)]">{counts.disabled}</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="mb-4">
        <CardContent className="pt-6">
          <div className="flex flex-wrap items-center gap-3">
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filtrer par ID, nom ou unité…"
              className="max-w-sm"
            />
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={showStandard} onChange={(e) => setShowStandard(e.target.checked)} />
              Standards
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={showCustom} onChange={(e) => setShowCustom(e.target.checked)} />
              Custom
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={showDisabled} onChange={(e) => setShowDisabled(e.target.checked)} />
              Désactivés
            </label>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Entrées</CardTitle>
          <CardDescription>
            Les entrées standards sont livrées avec le POC et ne peuvent pas être supprimées.
            Elles peuvent être désactivées ou renommées. Les custom sont éditables librement.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-md border border-[color:var(--color-border)]">
            <table className="w-full text-sm">
              <thead className="bg-[color:var(--color-muted)] text-left text-xs uppercase tracking-wide text-[color:var(--color-muted-foreground)]">
                <tr>
                  <th className="px-3 py-2">ID</th>
                  <th className="px-3 py-2">Nom</th>
                  <th className="px-3 py-2">Type</th>
                  <th className="px-3 py-2">Taille</th>
                  <th className="px-3 py-2">Unité</th>
                  <th className="px-3 py-2">État</th>
                  <th className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id} className="border-t border-[color:var(--color-border)]">
                    <td className="px-3 py-2 font-mono text-xs">
                      {e.dpt_id}
                      {e.kind === 'custom_handler' && (
                        <Code2 className="ml-2 inline size-3 text-amber-600" title="Handler Python" />
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {e.name}
                      {e.description && (
                        <div className="text-xs text-[color:var(--color-muted-foreground)]">{e.description}</div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant="outline">{e.kind}</Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-[color:var(--color-muted-foreground)]">
                      {e.size_bits} bits
                    </td>
                    <td className="px-3 py-2 text-xs">{e.unit || '—'}</td>
                    <td className="px-3 py-2">
                      {e.is_standard ? (
                        <Badge variant="outline">
                          <Package className="mr-1 size-3" />
                          Standard
                        </Badge>
                      ) : (
                        <Badge variant="warning">Custom</Badge>
                      )}
                      {!e.enabled && (
                        <Badge variant="outline" className="ml-1">Off</Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(e)}>
                        <Pencil />
                      </Button>
                      {!e.is_standard && (
                        <DeleteButton dptId={e.dpt_id} />
                      )}
                    </td>
                  </tr>
                ))}
                {entries.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-[color:var(--color-muted-foreground)]">
                      Aucune entrée à afficher.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <DptDialog
        open={creating || editing !== null}
        entry={editing}
        onClose={() => { setCreating(false); setEditing(null); }}
      />
    </>
  );
}

function DeleteButton({ dptId }: { dptId: string }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => api.deleteDptEntry(dptId),
    onSuccess: () => {
      toast.success(`DPT ${dptId} supprimé`);
      queryClient.invalidateQueries({ queryKey: ['dpt-registry'] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={() => {
        if (window.confirm(`Supprimer le DPT ${dptId} ? Les télégrammes utilisant ce DPT ne seront plus décodés.`)) {
          mutation.mutate();
        }
      }}
    >
      <Trash2 className="text-red-600" />
    </Button>
  );
}

function DptDialog({
  open, entry, onClose,
}: {
  open: boolean; entry: DptRegistryEntry | null; onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const isEdit = entry !== null;

  const [form, setForm] = useState<DptRegistryPayload>(() => ({
    dpt_id: entry?.dpt_id || '',
    name: entry?.name || '',
    size_bits: entry?.size_bits || 8,
    kind: entry?.kind || 'bytes',
    unit: entry?.unit || '',
    spec_json: entry?.spec_json || {},
    handler_code: entry?.handler_code || '',
    handler_name: entry?.handler_name || '',
    description: entry?.description || '',
    enabled: entry?.enabled ?? true,
  }));

  const [specJsonText, setSpecJsonText] = useState(() =>
    JSON.stringify(entry?.spec_json ?? {}, null, 2),
  );

  const mutation = useMutation({
    mutationFn: async () => {
      let specParsed: Record<string, unknown> = {};
      try {
        specParsed = specJsonText.trim() ? JSON.parse(specJsonText) : {};
      } catch (e) {
        throw new Error(`spec_json invalide : ${(e as Error).message}`);
      }
      const payload = { ...form, spec_json: specParsed };
      if (isEdit && entry) {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { dpt_id: _drop, ...patch } = payload;
        return api.updateDptEntry(entry.dpt_id, patch);
      }
      return api.createDptEntry(payload);
    },
    onSuccess: () => {
      toast.success(isEdit ? 'DPT mis à jour' : 'DPT créé');
      queryClient.invalidateQueries({ queryKey: ['dpt-registry'] });
      onClose();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const needsSpec = ['enum', 'bitfield', 'custom_struct'].includes(form.kind);
  const isHandler = form.kind === 'custom_handler';

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Modifier ${entry?.dpt_id}` : 'Ajouter un DPT'}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? 'Les DPT standards ne peuvent pas changer de kind.'
              : 'Ajoute un DPT custom qui sera pris en compte par le collector dans les 30 secondes.'}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label>DPT ID</Label>
              <Input
                value={form.dpt_id}
                onChange={(e) => setForm({ ...form, dpt_id: e.target.value })}
                className="mt-1 font-mono"
                placeholder="ex. custom.glt_store_1"
                disabled={isEdit}
              />
            </div>
            <div>
              <Label>Nom</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="mt-1"
                placeholder="ex. GLT Store position + orientation"
              />
            </div>
            <div>
              <Label>Type (kind)</Label>
              <select
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value as DptKind })}
                className={selectClass}
                disabled={isEdit && entry?.is_standard}
              >
                {KIND_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <p className="mt-1 text-xs text-[color:var(--color-muted-foreground)]">
                {KIND_OPTIONS.find((o) => o.value === form.kind)?.description}
              </p>
            </div>
            <div>
              <Label>Taille (bits)</Label>
              <Input
                type="number"
                value={form.size_bits}
                onChange={(e) => setForm({ ...form, size_bits: Number(e.target.value) })}
                className="mt-1"
              />
            </div>
            <div>
              <Label>Unité</Label>
              <Input
                value={form.unit || ''}
                onChange={(e) => setForm({ ...form, unit: e.target.value })}
                className="mt-1"
                placeholder="ex. °C, %, kWh"
              />
            </div>
            <div>
              <Label>État</Label>
              <label className="mt-1 flex h-9 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.enabled ?? true}
                  onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                />
                Activé
              </label>
            </div>
          </div>

          <div>
            <Label>Description</Label>
            <Input
              value={form.description || ''}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="mt-1"
            />
          </div>

          {needsSpec && (
            <div>
              <Label>Spec JSON</Label>
              <p className="mb-1 text-xs text-[color:var(--color-muted-foreground)]">
                {form.kind === 'enum' && 'Mapping valeur → nom : {"mapping": {"0": "Off", "1": "On", "2": "Auto"}}'}
                {form.kind === 'bitfield' && 'Champs bit à bit : {"fields": [{"name": "on", "offset": 0, "width": 1}]}'}
                {form.kind === 'custom_struct' && (
                  <>
                    Struct multi-champs : {'{"fields": [{"name": "phase_a", "type": "uint16", "scale": 0.01, "unit": "kWh"}]}'}
                    <br />
                    Types supportés : uint8/int8/uint16/int16/uint32/int32/float32
                  </>
                )}
              </p>
              <textarea
                value={specJsonText}
                onChange={(e) => setSpecJsonText(e.target.value)}
                className="mt-1 w-full min-h-[140px] rounded-md border border-[color:var(--color-input)] bg-transparent p-2 font-mono text-xs shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--color-ring)]"
                placeholder='{"fields": [...]}'
              />
            </div>
          )}

          {isHandler && (
            <>
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
                <AlertTriangle className="mr-1 inline size-4" />
                <strong>Attention sécurité :</strong> le code Python est exécuté dans le container
                collector sans sandbox. Un handler malveillant peut compromettre le service.
              </div>
              <div>
                <Label>Nom du handler (module)</Label>
                <Input
                  value={form.handler_name || ''}
                  onChange={(e) => setForm({ ...form, handler_name: e.target.value })}
                  className="mt-1"
                  placeholder="ex. glt_store"
                />
              </div>
              <div>
                <Label>Code Python (fonction decode(payload: bytes) → dict)</Label>
                <textarea
                  value={form.handler_code || ''}
                  onChange={(e) => setForm({ ...form, handler_code: e.target.value })}
                  className="mt-1 w-full min-h-[240px] rounded-md border border-[color:var(--color-input)] bg-transparent p-2 font-mono text-xs shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--color-ring)]"
                  placeholder={`def decode(payload: bytes) -> dict:
    """Retourne {value, value_num, unit, extra}."""
    if len(payload) < 2:
        return {"value": "", "value_num": None, "unit": "", "extra": {}}
    pos = payload[0]
    orient = payload[1] & 0x7F
    manual = bool(payload[1] & 0x80)
    return {
        "value": f"pos={pos}% orient={orient}%",
        "value_num": float(pos),
        "unit": "%",
        "extra": {
            "position": str(pos),
            "orientation": str(orient),
            "manual": str(manual),
        },
    }`}
                />
              </div>
            </>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? 'Sauvegarde…' : isEdit ? 'Enregistrer' : 'Créer'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
