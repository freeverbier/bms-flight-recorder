// Types partagés — miroir des schémas API côté backend.

export type GatewayMode = 'routing' | 'tunneling';
export type SourceMode = 'passive' | 'discovery' | 'polling';
export type ScanProtocol = 'bacnet' | 'knx';
export type ScanMode = 'bacnet_whois' | 'knx_search';

// Round 5 — Catégories APCI
export type ApciCategory =
  | 'runtime'
  | 'programming'
  | 'device'
  | 'memory'
  | 'authorization'
  | 'property'
  | 'diagnostic'
  | 'coupler'
  | 'other'
  | 'unknown';

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

// Frame — miroir bms.frames avec les colonnes Round 5
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
  // Round 5
  apci_category: ApciCategory | '';
  tpci: string;
  extra: Record<string, string>;
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
  // Round 7
  name_imported: string | null;
  dpt_imported: string | null;
  unit_imported: string | null;
  description_imported: string | null;
  is_modified: boolean;
  has_import: boolean;
}

// Round 5 — DPT Registry
export type DptKind =
  | 'bool'
  | 'uint8' | 'int8'
  | 'uint16' | 'int16'
  | 'uint32' | 'int32'
  | 'float16' | 'float32'
  | 'percent_u8' | 'angle_u8'
  | 'step_control'
  | 'time' | 'date'
  | 'string_ascii'
  | 'enum'
  | 'bitfield'
  | 'custom_struct'
  | 'custom_handler'
  | 'bytes';

export interface DptRegistryEntry {
  id: string;
  dpt_id: string;
  name: string;
  size_bits: number;
  kind: DptKind;
  unit: string;
  spec_json: Record<string, unknown>;
  handler_code?: string | null;
  handler_name?: string | null;
  is_standard: boolean;
  enabled: boolean;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface DptRegistryPayload {
  dpt_id: string;
  name: string;
  size_bits: number;
  kind: DptKind;
  unit?: string;
  spec_json?: Record<string, unknown>;
  handler_code?: string | null;
  handler_name?: string | null;
  description?: string;
  enabled?: boolean;
}

// KnxTelegram — payload SSE (enrichi Round 5)
export interface KnxTelegram {
  ts: string;
  gateway_id: string;
  source: string;
  destination: string;
  apci: string;
  apci_category: ApciCategory | '';
  tpci: string;
  value: string;
  unit: string;
  dpt: string;
  point_name: string;
  priority: string;
  hop_count: number;
  raw_hex: string;
  extra: Record<string, string>;
}

export interface Credential {
  id: string;
  name: string;
  kind: string;
  scope: string;
  fingerprint: string | null;
  created_at: string;
}

// --- Round 6 : Historique KNX ---
// Additions Round 6 à types.ts — à intégrer après les types existants.
// (Le patch-round6.sh insère automatiquement ces types.)

export interface KnxHistoryPoint {
  ts: string;            // ISO 8601 UTC
  value: number | null;  // null si aucun échantillon dans le bucket
  count: number;         // nombre de trames agrégées dans le bucket
}

export interface KnxHistoryMeta {
  address: string;
  point_name: string;
  dpt: string;
  unit: string;
  field: string;              // "value_num" ou "extra.KEY"
  bucket_s: number;           // taille du bucket en secondes
  from: string;               // ISO
  to: string;                 // ISO
  total_frames: number;
  available_fields: string[]; // ["value_num", "extra.height_pct", ...]
}

export interface KnxHistoryResponse {
  meta: KnxHistoryMeta;
  points: KnxHistoryPoint[];
}

export type HistoryRange = '1h' | '6h' | '24h' | '7d' | '30d';
// Round 11 additions à ui/src/lib/types.ts

export interface BacnetDevice {
  id: string;
  ip_address: string;
  port: number;
  device_id: number | null;
  vendor_id: number | null;
  max_apdu: number | null;
  segmentation: string | null;
  name: string | null;
  description: string | null;
  first_seen: string;
  last_seen: string;
  n_objects: number;
}

export interface BacnetObject {
  id: string;
  device_id: string;
  object_type: number;
  object_instance: number;
  object_ref: string;
  name: string | null;
  description: string | null;
  unit: string | null;
  source: string;
  name_imported: string | null;
  unit_imported: string | null;
  description_imported: string | null;
  first_seen: string;
  last_seen: string;
  device_ip: string;
  device_port: number;
  device_number: number | null;
  is_modified: boolean;
}

export interface BacnetFrame {
  ts: string;
  gateway_id: string;
  src: string;
  dst: string;
  bvlc_function: string;
  apdu_type: string;
  service: string;
  invoke_id: string;
  object_ref: string;
  property: string;
  value: string;
  value_num: number | null;
  unit: string;
  point_name: string;
  operation_detail: string;
  raw_hex: string;
  extra: Record<string, string>;
}


export interface BacnetScan {
  id: string;
  mode: string;
  target: string;
  port: number;
  status: 'queued' | 'running' | 'completed' | 'failed';
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  last_error: string | null;
}
