import { createFileRoute } from '@tanstack/react-router';
import { useCallback, useState, useEffect } from 'react';
import { PageHeader } from '@/components/app-shell';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/primitives';
import { TelegramList } from '@/features/knx/telegram-list';
import { HistoryTab } from '@/features/knx/history-chart';
import { GroupAddressTable } from '@/features/knx/group-address-table';
import { GatewaysPanel } from '@/features/knx-config/gateways-panel';
import { CredentialsPanel } from '@/features/knx-config/credentials-panel';
import { DptRegistryPanel } from '@/features/knx-config/dpt-registry-panel';
import type { HistoryRange } from '@/lib/types';

type KnxTab = 'config' | 'semantics' | 'frames' | 'history';

export const Route = createFileRoute('/knx-monitor')({
  component: KnxMonitor,
  validateSearch: (search: Record<string, unknown>): { tab?: KnxTab } => ({
    tab: (search.tab as KnxTab) || undefined,
  }),
});

function KnxMonitor() {
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  const [tab, setTabState] = useState<KnxTab>(search.tab || 'frames');
  const [historyAddress, setHistoryAddress] = useState('');
  const [historyField, setHistoryField] = useState('value_num');
  const [historyRange, setHistoryRange] = useState<HistoryRange>('24h');

  const setTab = useCallback((t: KnxTab) => {
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
        title="KNX"
        subtitle="Sniffing passif KNX/IP — routing multicast + tunneling"
      />
      <Tabs value={tab} onValueChange={(v) => setTab(v as KnxTab)}>
        <TabsList>
          <TabsTrigger value="config">Configuration</TabsTrigger>
          <TabsTrigger value="semantics">Sémantique</TabsTrigger>
          <TabsTrigger value="frames">Trames</TabsTrigger>
          <TabsTrigger value="history">Historique</TabsTrigger>
        </TabsList>

        <TabsContent value="config">
          <div className="flex flex-col gap-4">
            <GatewaysPanel />
            <CredentialsPanel />
          </div>
        </TabsContent>

        <TabsContent value="semantics">
          <div className="flex flex-col gap-4">
            <DptRegistryPanel />
            <Card>
              <CardContent className="pt-5">
                <GroupAddressTable />
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="frames">
          <Card>
            <CardContent className="pt-5">
              <TelegramList onShowHistory={openHistory} />
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
      </Tabs>
    </>
  );
}
