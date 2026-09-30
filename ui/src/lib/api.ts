// Client HTTP simple, typé.

import type {DptRegistryEntry, DptRegistryPayload,
  Frame, Gateway, Summary, TelemetryValue,
  ProtocolSource, DataPoint, ScanJob, DiscoveredDevice,
  PromoteDevicePayload, PromoteDeviceResult,
  KnxGroupAddress, Credential,
  KnxHistoryResponse, BacnetDevice, BacnetObject, BacnetScan, BacnetScan} from './types';

const BASE = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    ...init,
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body?.detail) message = String(body.detail);
    } catch {
      /* pas de corps JSON */
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const api = {
  summary: () => request<Summary>('/summary'),
  frames: (limit = 50, protocol = '', apci_category = '') => {
    const qs = new URLSearchParams();
    qs.set('limit', String(limit));
    if (protocol) qs.set('protocol', protocol);
    if (apci_category) qs.set('apci_category', apci_category);
    return request<Frame[]>(`/frames?${qs.toString()}`);
  },
  values: (limit = 100) => request<TelemetryValue[]>(`/values?limit=${limit}`),

  gateways: () => request<Gateway[]>('/gateways'),
  deleteGateway: (id: string) =>
    request<void>(`/gateways/${id}`, { method: 'DELETE' }),
  createGateway: (payload: Partial<Gateway>) =>
    request<Gateway>('/gateways', { method: 'POST', body: JSON.stringify(payload) }),

  sources: (protocol?: 'bacnet' | 'modbus') =>
    request<ProtocolSource[]>(protocol ? `/sources?protocol=${protocol}` : '/sources'),
  createSource: (payload: Partial<ProtocolSource>) =>
    request<ProtocolSource>('/sources', { method: 'POST', body: JSON.stringify(payload) }),
  points: (sourceId: string) => request<DataPoint[]>(`/sources/${sourceId}/points`),
  createPoint: (sourceId: string, payload: Partial<DataPoint>) =>
    request<DataPoint>(`/sources/${sourceId}/points`, {
      method: 'POST', body: JSON.stringify(payload),
    }),

  scans: () => request<ScanJob[]>('/scans'),
  createScan: (payload: {
    protocol: 'bacnet' | 'knx'; mode: 'bacnet_whois' | 'knx_search';
    target: string; port: number;
  }) => request<ScanJob>('/scans', { method: 'POST', body: JSON.stringify(payload) }),
  scanDevices: (scanId: string) =>
    request<DiscoveredDevice[]>(`/scans/${scanId}/devices`),
  promoteDevice: (scanId: string, deviceId: string, payload: PromoteDevicePayload) =>
    request<PromoteDeviceResult>(`/scans/${scanId}/devices/${deviceId}/promote`, {
      method: 'POST', body: JSON.stringify(payload),
    }),

  knxGroupAddresses: (search?: string) =>
    request<KnxGroupAddress[]>(
      `/knx/group-addresses${search ? `?search=${encodeURIComponent(search)}` : ''}`,
    ),
  updateKnxGroupAddress: (address: string, patch: Partial<KnxGroupAddress>) =>
    request<{ ok: true }>(`/knx/group-addresses/${encodeURIComponent(address)}`, {
      method: 'PATCH', body: JSON.stringify(patch),
    }),

  // Round 7 : restauration et suppression
  resetKnxGroupAddress: (address: string) =>
    request<{ ok: true; restored_from: string }>(
      `/knx/group-addresses/${encodeURIComponent(address)}/reset`,
      { method: 'POST' },
    ),

  deleteKnxGroupAddress: (address: string) =>
    request<void>(
      `/knx/group-addresses/${encodeURIComponent(address)}`,
      { method: 'DELETE' },
    ),

  // Round 5 — DPT Registry
  dptRegistry: (includeDisabled = false) =>
    request<DptRegistryEntry[]>(`/knx/dpt-registry${includeDisabled ? '?include_disabled=true' : ''}`),
  createDptEntry: (payload: DptRegistryPayload) =>
    request<{ id: string; dpt_id: string }>('/knx/dpt-registry', {
      method: 'POST', body: JSON.stringify(payload),
    }),
  updateDptEntry: (dptId: string, payload: Partial<DptRegistryPayload>) =>
    request<{ ok: true; changed: number }>(`/knx/dpt-registry/${encodeURIComponent(dptId)}`, {
      method: 'PATCH', body: JSON.stringify(payload),
    }),
  deleteDptEntry: (dptId: string) =>
    request<void>(`/knx/dpt-registry/${encodeURIComponent(dptId)}`, { method: 'DELETE' }),

  importEsf: async (file: File) => {
    const body = new FormData(); body.append('file', file);
    const r = await fetch(`${BASE}/knx/import/esf`, { method: 'POST', body });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json() as Promise<{ imported: number; updated: number; total: number }>;
  },
  importKnxproj: async (file: File) => {
    const body = new FormData(); body.append('file', file);
    const r = await fetch(`${BASE}/knx/import/knxproj`, { method: 'POST', body });
    if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { detail?: string })?.detail || `HTTP ${r.status}`);
    return r.json() as Promise<{ imported: number; updated: number; total: number }>;
  },
  importKeyring: async (file: File, password: string, scope = 'global') => {
    const body = new FormData();
    body.append('file', file); body.append('password', password); body.append('scope', scope);
    const r = await fetch(`${BASE}/knx/import/keyring`, { method: 'POST', body });
    if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { detail?: string })?.detail || `HTTP ${r.status}`);
    return r.json() as Promise<{ id: string; summary: Record<string, unknown> }>;
  },

  credentials: () => request<Credential[]>('/credentials'),

  // Round 6 : historique bucketisé pour graphique
  knxHistory: (address: string, since: string = '24h', field: string = 'value_num') => {
    const qs = new URLSearchParams();
    qs.set('address', address);
    qs.set('since', since);
    qs.set('field', field);
    return request<KnxHistoryResponse>(`/knx/history?${qs.toString()}`);
  },

  // ===== Round 11 : BACnet =====
  bacnetDevices: () =>
    request<BacnetDevice[]>('/bacnet/devices'),

  bacnetCreateDevice: (payload: Partial<BacnetDevice>) =>
    request<{ id: string; ip_address: string; port: number }>('/bacnet/devices', {
      method: 'POST', body: JSON.stringify(payload),
    }),

  bacnetDeleteDevice: (id: string) =>
    request<void>(`/bacnet/devices/${id}`, { method: 'DELETE' }),

  bacnetDiscover: (payload: { target?: string; port?: number }) =>
    request<{ ok: true; target: string; port: number; started_at: string }>(
      '/bacnet/discover',
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  bacnetDiscoverObjects: (deviceId: string) =>
    request<{ ok: true; job_id: string; device_uuid: string }>(
      `/bacnet/devices/${deviceId}/discover-objects`,
      { method: 'POST' },
    ),

  bacnetObjects: (opts: { device_id?: string; search?: string; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.device_id) params.set('device_id', opts.device_id);
    if (opts.search) params.set('search', opts.search);
    if (opts.limit) params.set('limit', String(opts.limit));
    return request<BacnetObject[]>(`/bacnet/objects${params.toString() ? '?' + params.toString() : ''}`);
  },

  bacnetUpdateObject: (id: string, patch: Partial<BacnetObject>) =>
    request<{ ok: true }>(`/bacnet/objects/${id}`, {
      method: 'PATCH', body: JSON.stringify(patch),
    }),

  bacnetResetObject: (id: string) =>
    request<{ ok: true }>(`/bacnet/objects/${id}/reset`, { method: 'POST' }),

  bacnetHistory: (address: string, since: string = '24h', field: string = 'value_num') => {
    const p = new URLSearchParams({ address, since, field });
    return request<{ points: { ts: string; value: number | null }[] }>(
      `/bacnet/history?${p.toString()}`,
    );
  },
  bacnetScans: () =>
    request<BacnetScan[]>('/bacnet/scans'),

  createScan: (payload: { protocol: 'bacnet' | 'knx'; mode: 'bacnet_whois' | 'knx_search'; target: string; port: number }) =>
    request<ScanJob>('/scans', { method: 'POST', body: JSON.stringify(payload) }),

  deleteGateway: (id: string) =>
    request<void>(`/gateways/${id}`, { method: 'DELETE' }),

};
