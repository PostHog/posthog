import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type {
    PatchedSignalScoutConfigUpdateApi,
    SignalScoutConfigApi,
} from 'products/signals/frontend/generated/api.schemas'

import { ScoutAllowedDomainsEditor } from './ScoutAllowedDomainsEditor'

const config: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-vendor-status',
    description: 'Watches a vendor status page.',
    scout_origin: 'custom',
    owners: [],
    enabled: true,
    status: 'active',
    pause_reason: null,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: null,
    output_destinations: {},
    structured_output_schema: null,
    mcp_gateway_server_ids: [],
    write_scopes: [],
    network_access: 'custom',
    allowed_domains: ['status.example.com', '*.example.org'],
    model: null,
    last_run_at: null,
    consecutive_failure_count: 0,
    status_changed_at: null,
    auto_pause_exempt: false,
    tags: [],
    source_product: null,
    source_id: null,
    created_at: '2026-08-05T00:00:00Z',
}

function ScoutAllowedDomainsPreview({ initialDomains }: { initialDomains: string[] }): JSX.Element {
    const [allowedDomains, setAllowedDomains] = useState(initialDomains)
    const updateConfig = (_configId: string, updates: PatchedSignalScoutConfigUpdateApi): void => {
        if (updates.allowed_domains) {
            setAllowedDomains(updates.allowed_domains)
        }
    }

    return (
        // The settings form sits in the fleet row, so it has to hold up at about the width a
        // 1280px window leaves once the nav and a side panel are open.
        <div className="flex w-[20rem] flex-col gap-2 rounded border border-primary bg-bg-light p-4">
            <span className="text-xs text-default">Custom domains</span>
            <ScoutAllowedDomainsEditor
                config={{ ...config, allowed_domains: allowedDomains }}
                onUpdate={updateConfig}
            />
        </div>
    )
}

const meta: Meta = {
    title: 'Scenes-Inbox/Scout allowed domains',
    parameters: { layout: 'centered' },
}

export default meta

type Story = StoryObj

export const WithDomains: Story = {
    render: () => <ScoutAllowedDomainsPreview initialDomains={config.allowed_domains as string[]} />,
}

export const Empty: Story = {
    render: () => <ScoutAllowedDomainsPreview initialDomains={[]} />,
}
