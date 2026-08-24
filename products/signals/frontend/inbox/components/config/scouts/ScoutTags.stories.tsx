import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type {
    PatchedSignalScoutConfigUpdateApi,
    SignalScoutConfigApi,
} from 'products/signals/frontend/generated/api.schemas'

import { ScoutTagBadge } from './ScoutBadges'
import { ScoutTagsEditor } from './ScoutTagsEditor'
import { ScoutTagsFilter } from './ScoutTagsFilter'

const config: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-revenue-watch',
    description: 'Watches revenue changes.',
    scout_origin: 'custom',
    enabled: true,
    status: 'active',
    pause_reason: null,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: null,
    output_destinations: {},
    structured_output_schema: null,
    mcp_gateway_server_ids: [],
    network_access: 'trusted',
    model: null,
    last_run_at: null,
    consecutive_failure_count: 0,
    status_changed_at: null,
    auto_pause_exempt: false,
    tags: ['on-call', 'revenue'],
    source_product: null,
    source_id: null,
    created_at: '2026-08-05T00:00:00Z',
}

function ScoutTagsPreview(): JSX.Element {
    const [tags, setTags] = useState(config.tags ?? [])
    const [selected, setSelected] = useState<string[]>(['revenue'])
    const updateConfig = (_configId: string, updates: PatchedSignalScoutConfigUpdateApi): void => {
        if (updates.tags) {
            setTags(updates.tags)
        }
    }
    const options = [
        { tag: 'revenue', count: 4 },
        { tag: 'on-call', count: 2 },
        { tag: 'security', count: 1 },
    ]

    return (
        <div className="flex w-[32rem] flex-col gap-6 rounded border border-primary bg-bg-light p-4">
            <div className="flex flex-col gap-2">
                <span className="text-xs font-medium text-default">Scout badges</span>
                <div className="flex flex-wrap gap-1">
                    {tags.map((tag) => (
                        <ScoutTagBadge key={tag} tag={tag} />
                    ))}
                </div>
            </div>
            <div className="flex flex-col gap-2">
                <span className="text-xs font-medium text-default">Tags</span>
                <ScoutTagsEditor config={{ ...config, tags }} onUpdate={updateConfig} />
            </div>
            <div className="flex items-center gap-2">
                <span className="text-xs text-muted">Tagged</span>
                <ScoutTagsFilter
                    options={options}
                    selected={selected}
                    onToggle={(tag) =>
                        setSelected(
                            selected.includes(tag)
                                ? selected.filter((candidate) => candidate !== tag)
                                : [...selected, tag]
                        )
                    }
                    onClear={() => setSelected([])}
                />
            </div>
        </div>
    )
}

const meta: Meta = {
    title: 'Scenes-Inbox/Scout tags',
    parameters: { layout: 'centered' },
}

export default meta

type Story = StoryObj

export const EditorAndFilter: Story = {
    render: () => <ScoutTagsPreview />,
}
