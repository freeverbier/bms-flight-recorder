// Client HTTP simple, typé, sans surprise.

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
  summary: () => request<import('./types').Summary>('/summary'),
  frames: (limit = 50) => request<import('./types').Frame[]>(`/frames?limit=${limit}`),
  values: (limit = 100) => request<import('./types').TelemetryValue[]>(`/values?limit=${limit}`),

  gateways: () => request<import('./types').Gateway[]>('/gateways'),
  createGateway: (payload: Partial<import('./types').Gateway>) =>
    request<import('./types').Gateway>('/gateways', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  sources: (protocol?: 'bacnet' | 'modbus') =>
    request<import('./types').ProtocolSource[]>(
      protocol ? `/sources?protocol=${protocol}` : '/sources',
    ),
  createSource: (payload: Partial<import('./types').ProtocolSource>) =>
    request<import('./types').ProtocolSource>('/sources', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  points: (sourceId: string) =>
    request<import('./types').DataPoint[]>(`/sources/${sourceId}/points`),
  createPoint: (sourceId: string, payload: Partial<import('./types').DataPoint>) =>
    request<import('./types').DataPoint>(`/sources/${sourceId}/points`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  scans: () => request<import('./types').ScanJob[]>('/scans'),
  createScan: (payload: {
    protocol: 'bacnet' | 'knx';
    mode: 'bacnet_whois' | 'knx_search';
    target: string;
    port: number;
  }) =>
    request<import('./types').ScanJob>('/scans', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  scanDevices: (scanId: string) =>
    request<import('./types').DiscoveredDevice[]>(`/scans/${scanId}/devices`),
  promoteDevice: (
    scanId: string,
    deviceId: string,
    payload: import('./types').PromoteDevicePayload,
  ) =>
    request<import('./types').PromoteDeviceResult>(
      `/scans/${scanId}/devices/${deviceId}/promote`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  knxGroupAddresses: (search?: string) =>
    request<import('./types').KnxGroupAddress[]>(
      `/knx/group-addresses${search ? `?search=${encodeURIComponent(search)}` : ''}`,
    ),
  updateKnxGroupAddress: (address: string, patch: Partial<import('./types').KnxGroupAddress>) =>
    request<{ ok: true }>(`/knx/group-addresses/${encodeURIComponent(address)}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  importEsf: async (file: File) => {
    const body = new FormData();
    body.append('file', file);
    const response = await fetch(`${BASE}/knx/import/esf`, { method: 'POST', body });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json() as Promise<{ imported: number; updated: number; total: number }>;
  },
  importKnxproj: async (file: File) => {
    const body = new FormData();
    body.append('file', file);
    const response = await fetch(`${BASE}/knx/import/knxproj`, { method: 'POST', body });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail?.detail || `HTTP ${response.status}`);
    }
    return response.json() as Promise<{ imported: number; updated: number; total: number }>;
  },
  importKeyring: async (file: File, password: string, scope = 'global') => {
    const body = new FormData();
    body.append('file', file);
    body.append('password', password);
    body.append('scope', scope);
    const response = await fetch(`${BASE}/knx/import/keyring`, { method: 'POST', body });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail?.detail || `HTTP ${response.status}`);
    }
    return response.json() as Promise<{ id: string; summary: Record<string, unknown> }>;
  },

  credentials: () => request<import('./types').Credential[]>('/credentials'),
};
