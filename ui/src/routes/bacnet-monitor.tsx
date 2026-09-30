import { createFileRoute } from '@tanstack/react-router';
import { useCallback, useState, useEffect } from 'react';
import { PageHeader } from '@/components/app-shell';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/primitives';
import { FrameList } from '@/features/bacnet/frame-list';
import { HistoryTab, type HistoryRange } from '@/features/bacnet/history-chart';
import { DeviceTable } from '@/features/bacnet/device-table';
import { ObjectTable } from '@/features/bacnet/object-table';
import { SourcesPanel } from '@/features/bacnet-config/sources-panel';
import { ScanPanel } from '@/features/bacnet-config/scan-panel';

type BacnetTab = 'config' | 'frames' | 'history' | 'objects';

export const Route = createFileRoute('/bacnet-monitor')({
  component: BacnetMonitor,
  validateSearch: (search: Record<string, unknown>): { tab?: BacnetTab } => ({
    tab: (search.tab as BacnetTab) || undefined,
  }),
});

function BacnetMonitor() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  const [tab, setTabState] = useState<BacnetTab>(search.tab || 'frames');
  const [historyAddress, setHistoryAddress] = useState('');
  const [historyField, setHistoryField] = useState('value_num');
  const [historyRange, setHistoryRange] = useState<HistoryRange>('24h');
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | undefined>();

  const setTab = useCallback((t: BacnetTab) => {
    setTabState(t);
    navigate({ search: { tab: t }, replace: true });
  }, [navigate]);

  useEffect(() => {
    if (search.tab && search.tab !== tab) setTabState(search.tab);
  }, [search.tab]);

  const openHistory = useCallback((addressAndField: string) => {
    const [address, field] = addressAndField.split('|');
    setHistoryAddress(address);
    setHistoryField(field || 'value_num');
    setTab('history');
  }, [setTab]);

  return (
    <>
      <PageHeader
        title="BACnet"
        subtitle="Sniffer passif UDP 47808 — décodage BACnet/IP + auto-découverte"
      />
      <Tabs value={tab} onValueChange={(v) => setTab(v as BacnetTab)}>
        <TabsList>
          <TabsTrigger value="config">Configuration</TabsTrigger>
          <TabsTrigger value="frames">Trames</TabsTrigger>
          <TabsTrigger value="history">Historique</TabsTrigger>
          <TabsTrigger value="objects">Vue objets & topologie</TabsTrigger>
        </TabsList>

        <TabsContent value="config">
          <div className="flex flex-col gap-4">
            <SourcesPanel />
            <ScanPanel />
          </div>
        </TabsContent>

        <TabsContent value="frames">
          <Card>
            <CardContent className="pt-5">
              <FrameList onShowHistory={openHistory} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="history">
          <HistoryTab
            initialAddress={historyAddress}
            initialField={historyField}
            initialRange={historyRange}
            onAddressChange={setHistoryAddress}
            onFieldChange={setHistoryField}
            onRangeChange={setHistoryRange}
          />
        </TabsContent>

        <TabsContent value="objects">
          <div className="flex flex-col gap-4">
            <DeviceTable
              selectedDeviceId={selectedDeviceId}
              onSelectDevice={setSelectedDeviceId}
            />
            <ObjectTable
              deviceId={selectedDeviceId}
              onShowHistory={openHistory}
            />
          </div>
        </TabsContent>
      </Tabs>
    </>
  );
}
