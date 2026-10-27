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

const filter = (overrides: Partial<ErrorTrackingBuiltInFilterApi>): ErrorTrackingBuiltInFilterApi => ({
    key: 'web_crawlers',
    name: 'Web crawlers and bots',
    description: 'Drop exceptions from search engines, AI crawlers, uptime monitors and headless browsers.',
    evaluation: 'server',
    enabled: false,
    disabled_reason: null,
    ...overrides,
})

// A narrow container matches a settings scene with the side panel open.
export const States: Story = {
    render: () => (
        <div className="w-[520px] rounded border bg-surface-primary divide-y">
            <BuiltInFilterRow filter={filter({})} saving={false} editDisabledReason={null} onSetEnabled={() => {}} />
            <BuiltInFilterRow
                filter={filter({
                    key: 'chunk_load_errors',
                    name: 'Chunk load errors',
                    description:
                        'Drop errors from lazy-loaded scripts that fail to load, which often happens after a deploy.',
                    evaluation: 'client',
                    enabled: true,
                })}
                saving={false}
                editDisabledReason={null}
                onSetEnabled={() => {}}
            />
            <BuiltInFilterRow
                filter={filter({
                    key: 'legacy_browsers',
                    name: 'Legacy browsers',
                    description:
                        'Drop exceptions from Internet Explorer, Chrome before 87, Edge before 88, Firefox before 78, Safari before 14 and Opera before 73.',
                    enabled: true,
                    disabled_reason: 'Invalid regex: unclosed group',
                })}
                saving={false}
                editDisabledReason={null}
                onSetEnabled={() => {}}
            />
            <BuiltInFilterRow
                filter={filter({
                    key: 'localhost',
                    name: 'Local development',
                    description: 'Drop exceptions from pages on localhost, a loopback address or a file: URL.',
                })}
                saving={false}
                editDisabledReason="You don't have edit access to error tracking"
                onSetEnabled={() => {}}
            />
        </div>
    ),
}
