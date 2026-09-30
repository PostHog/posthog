import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

import { scratchpadLogic } from '../../logics/scratchpadLogic'
import { ScratchpadPanel } from './ScratchpadPanel'

const SCRATCHPAD_URL = '/api/projects/:team_id/signals/scout/scratchpad/'
const REPORTS_URL = '/api/projects/:team_id/signals/reports/:id/'
const REPORT_ID = '01a0918c-5f5f-74c4-b539-c634a8cb990a'

// The panel gets about 520 px once the nav and a side panel are open. That is the width the
// stacked layout exists for, so it gets its own story rather than a note in a review.
const NARROW_WIDTH = 520

function entry(overrides: Partial<ScratchpadEntryApi> & { key: string }): ScratchpadEntryApi {
    return {
        content: '',
        created_at: '2026-07-31T09:00:00Z',
        updated_at: '2026-09-11T17:15:00Z',
        expires_at: null,
        created_by_skill: null,
        created_by_run_id: null,
        created_by_run_url: null,
        ...overrides,
    } as ScratchpadEntryApi
}

const ENTRIES: ScratchpadEntryApi[] = [
    entry({
        key: 'pattern:apm:p95-regression-window',
        created_by_skill: 'signals-scout-apm',
        content:
            'Regressions on the query endpoint show up first in the **15-minute p95**, not p50. Compare against the same weekday last week, not yesterday.\n\n- Monday mornings carry a warm-cache dip that reads as a regression against Sunday.\n- Ruled out: a 7-day rolling mean. It smooths the weekday shape away.',
    }),
    entry({
        key: `judged:${REPORT_ID}`,
        created_by_skill: 'signals-scout-inbox-validation',
        updated_at: '2026-09-11T17:14:00Z',
        created_at: '2026-09-11T17:14:00Z',
        content: 'Passed. The summary names an internal dashboard, which is fine for an internal surface.',
    }),
    entry({
        key: 'followup:billing_spikes:34302',
        created_by_skill: 'signals-scout-customer-analytics-billing-and-usage',
        updated_at: '2026-09-11T17:12:00Z',
        created_at: '2026-09-11T17:12:00Z',
        expires_at: '2026-09-21T00:00:00Z',
        content: 'Pending. Validate after the next billing period closes, once a second month of data exists.',
    }),
    entry({
        key: 'baseline:slo_monitoring:export-error-rate',
        created_by_skill: 'signals-scout-health-checks',
        updated_at: '2026-09-11T17:09:00Z',
        created_at: '2026-07-12T09:00:00Z',
        content: 'Weekday export error rate sits at 0.4% of jobs. A weekend reading is not comparable.',
    }),
    entry({
        key: 'noise:logs:redis-timeout-startup',
        created_by_skill: 'signals-scout-logs',
        updated_at: '2026-09-11T17:04:00Z',
        created_at: '2026-08-14T09:00:00Z',
        content: 'The Redis timeout burst on pod start is expected. It clears once the connection pool warms.',
    }),
    entry({
        key: 'pattern:impl:reports-research',
        created_by_skill: 'pipeline:report-research',
        updated_at: '2026-09-11T16:47:00Z',
        created_at: '2026-06-02T09:00:00Z',
        content: 'Research that opens with the linked issue reads faster than research that opens with the query.',
    }),
]

type Story = StoryObj<typeof ScratchpadPanel>

const meta: Meta<typeof ScratchpadPanel> = {
    component: ScratchpadPanel,
    title: 'Scenes-App/Signals/ScratchpadPanel',
    tags: ['autodocs'],
    parameters: { mockDate: '2026-09-11T20:15:00Z' },
}
export default meta

function Panel({ width }: { width?: number }): JSX.Element {
    return (
        <div style={{ width: width ?? '100%' }}>
            <ScratchpadPanel />
        </div>
    )
}

export const Populated: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                [SCRATCHPAD_URL]: () => [200, ENTRIES],
                [REPORTS_URL]: () => [200, { id: REPORT_ID, title: 'Export error rate doubled on Tuesday' }],
            },
        })
        return <Panel />
    },
}

export const PopulatedNarrow: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                [SCRATCHPAD_URL]: () => [200, ENTRIES],
                [REPORTS_URL]: () => [200, { id: REPORT_ID, title: 'Export error rate doubled on Tuesday' }],
            },
        })
        return <Panel width={NARROW_WIDTH} />
    },
}

export const Loading: Story = {
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '.LemonSkeleton',
        },
    },
    render: () => {
        useStorybookMocks({ get: { [SCRATCHPAD_URL]: () => new Promise(() => {}) } })
        return <Panel />
    },
}

export const LoadingNarrow: Story = {
    parameters: Loading.parameters,
    render: () => {
        useStorybookMocks({ get: { [SCRATCHPAD_URL]: () => new Promise(() => {}) } })
        return <Panel width={NARROW_WIDTH} />
    },
}

export const Empty: Story = {
    render: () => {
        useStorybookMocks({ get: { [SCRATCHPAD_URL]: () => [200, []] } })
        return <Panel />
    },
}

/** A search nothing matches: the ledger is empty but the memory is not, so the state offers a way back. */
export const FilteredEmpty: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                [SCRATCHPAD_URL]: ({ request }) => [200, new URL(request.url).searchParams.get('text') ? [] : ENTRIES],
                [REPORTS_URL]: () => [200, { id: REPORT_ID, title: 'Export error rate doubled on Tuesday' }],
            },
        })
        useEffect(() => {
            scratchpadLogic.findMounted()?.actions.setSearchText('nothing in memory matches this')
        }, [])
        return <Panel />
    },
}

export const LoadFailed: Story = {
    render: () => {
        useStorybookMocks({ get: { [SCRATCHPAD_URL]: () => [500, {}] } })
        return <Panel />
    },
}
