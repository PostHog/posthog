import { Meta, StoryObj } from '@storybook/react'

import type { ErrorTrackingBuiltInFilterApi } from '../../../generated/api.schemas'
import { BuiltInFilterRow } from './BuiltInFilterRow'

const meta: Meta<typeof BuiltInFilterRow> = {
    title: 'ErrorTracking/BuiltInFilterRow',
    component: BuiltInFilterRow,
    parameters: {
        layout: 'padded',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof BuiltInFilterRow>

const FILTERS: ErrorTrackingBuiltInFilterApi[] = [
    {
        key: 'web_crawlers',
        name: 'Web crawlers and bots',
        description: 'Drop exceptions from search engines, AI crawlers, uptime monitors and headless browsers.',
        evaluation: 'server',
        enabled: true,
        disabled_reason: null,
    },
    {
        key: 'localhost',
        name: 'Local development',
        description: 'Drop exceptions from pages on localhost, a loopback address or a file: URL.',
        evaluation: 'server',
        enabled: false,
        disabled_reason: null,
    },
    {
        key: 'legacy_browsers',
        name: 'Legacy browsers',
        description:
            'Drop exceptions from Internet Explorer, Chrome before 87, Edge before 88, Firefox before 78, Safari before 14 and Opera before 73.',
        evaluation: 'server',
        enabled: true,
        disabled_reason: null,
    },
    {
        key: 'react_hydration_errors',
        name: 'React hydration errors',
        description: "Drop React errors about server-rendered HTML that doesn't match the page in the browser.",
        evaluation: 'client',
        enabled: false,
        disabled_reason: null,
    },
    {
        key: 'chunk_load_errors',
        name: 'Chunk load errors',
        description: 'Drop errors from lazy-loaded scripts that fail to load, which often happens after a deploy.',
        evaluation: 'client',
        enabled: true,
        disabled_reason: null,
    },
    {
        key: 'resize_observer_loop',
        name: 'ResizeObserver loop errors',
        description: 'Drop the ResizeObserver loop warning that browsers report as an error.',
        evaluation: 'client',
        enabled: false,
        disabled_reason: null,
    },
]

// A narrow container matches a settings scene with the side panel open.
export const SomeRulesOn: Story = {
    render: () => (
        <div className="w-[520px] rounded border bg-surface-primary divide-y">
            {FILTERS.map((filter) => (
                <BuiltInFilterRow
                    key={filter.key}
                    filter={filter}
                    saving={false}
                    editDisabledReason={null}
                    onSetEnabled={() => {}}
                />
            ))}
        </div>
    ),
}
