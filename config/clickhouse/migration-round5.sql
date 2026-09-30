-- Migration Round 5 : enrichissement bms.frames pour couvrir APCI complet + DPT dynamiques
--
-- 3 nouvelles colonnes :
--   apci_category   : catégorie APCI ('runtime'|'programming'|'device'|'memory'|
--                     'authorization'|'property'|'diagnostic'|'coupler'|'other'|'unknown')
--   tpci            : type de trame transport ('T_Data_Group'|'T_Connect'|...)
--   extra           : Map(String, String) pour les champs additionnels des décodeurs
--                     (obj_index, prop_id, count, address, data, seq, fields de struct...)

ALTER TABLE bms.frames ADD COLUMN IF NOT EXISTS apci_category LowCardinality(String) DEFAULT '';
ALTER TABLE bms.frames ADD COLUMN IF NOT EXISTS tpci LowCardinality(String) DEFAULT '';
ALTER TABLE bms.frames ADD COLUMN IF NOT EXISTS extra Map(String, String) DEFAULT map();

-- Index bloom_filter pour filtrer rapidement par catégorie
CREATE INDEX IF NOT EXISTS idx_apci_category ON bms.frames (apci_category) TYPE bloom_filter GRANULARITY 4;
