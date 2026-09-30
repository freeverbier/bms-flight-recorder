// Types partagés — miroir des schémas API côté backend.

export type GatewayMode = 'routing' | 'tunneling';
export type SourceMode = 'passive' | 'discovery' | 'polling';
export type ScanProtocol = 'bacnet' | 'knx';
export type ScanMode = 'bacnet_whois' | 'knx_search';

export interface Gateway {
  id: string;
  name: string;
  site: string;
  line: string;
  mode: GatewayMode;
  host?: string;
  port: number;
  multicast_group?: string;
  secure: boolean;
  credential_id?: string;
  enabled: boolean;
  status: string;
  last_seen?: string;
  last_error?: string;
}

export interface ProtocolSource {
  id: string;
  protocol: 'bacnet' | 'modbus';
  name: string;
  site: string;
  mode: SourceMode;
  host?: string;
  port: number;
  enabled: boolean;
  status: string;
  last_error?: string;
  config: Record<string, unknown>;
}

export interface DataPoint {
  id: string;
  source_id: string;
  name: string;
  point_key: string;
  address?: number;
  function_code?: number;
  data_type?: string;
  scale: number;
  unit?: string;
  poll_seconds: number;
  enabled: boolean;
  config?: Record<string, unknown>;
}

// Frame — miroir exact de bms.frames (schéma unifié Round 1)
export interface Frame {
  ts: string;
  protocol: string;
  source_kind: string;
  source_id: string;
  src: string;
  dst: string;
  operation: string;
  value: string;
  value_num: number | null;
  unit: string;
  dpt: string;
  point_name: string;
  priority: string;
  hop_count: number;
  frame_len: number;
  status: string;
}

export interface TelemetryValue {
  ts: string;
  protocol: string;
  point_key: string;
  point_name: string;
  value?: number;
  value_text?: string;
  unit: string;
  quality: string;
  origin: string;
}

export interface Summary {
  packets_per_second: number;
  frames_today: number;
  active_gateways: number;
  packet_loss_percent: number;
  protocols: { name: string; percent: number; count: number }[];
}

export interface ScanJob {
  id: string;
  protocol: ScanProtocol;
  mode: ScanMode;
  target: string;
  port: number;
  status: string;
  device_count: number;
  created_at?: string;
  completed_at?: string;
  last_error?: string;
}

export interface DiscoveredDevice {
  id: string;
  scan_id: string;
  protocol: string;
  address: string;
  name: string;
  metadata: Record<string, string | number | null>;
  promoted_gateway_id: string | null;
}

export interface PromoteDevicePayload {
  name: string;
  site: string;
  mode: GatewayMode;
}

export interface PromoteDeviceResult {
  gateway_id: string;
  already_existed: boolean;
}

export interface KnxGroupAddress {
  address: string;
  name: string;
  dpt: string | null;
  description: string | null;
  unit: string | null;
  source: string;
  updated_at: string;
}

export interface KnxTelegram {
  ts: string;
  gateway_id: string;
  source: string;
  destination: string;
  apci: string;
  value: string;
  unit: string;
  dpt: string;
  point_name: string;
  priority: string;
  hop_count: number;
  raw_hex: string;
}

export interface Credential {
  id: string;
  name: string;
  kind: string;
  scope: string;
  fingerprint: string | null;
  created_at: string;
}
