import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { NotebookAppRefreshStatusApi } from '../generated/api.schemas'
import { RefreshDetails } from './NotebookAppRefreshPanel'

const lastSuccess = '2026-02-19T09:01:00Z'
const initial: NotebookAppRefreshStatusApi = {
    published_revision: 3,
    revision: 3,
    enabled: true,
    interval_minutes: 60,
    freshness_minutes: 90,
    next_due_at: '2026-02-19T12:00:00Z',
    last_success_at: lastSuccess,
    stale: true,
    history: [
        {
            revision: 3,
            due_at: '2026-02-19T11:00:00Z',
            finished_at: '2026-02-19T11:01:00Z',
            status: 'failed',
            detail: 'Could not refresh the SQL results.',
            output_count: 0,
        },
        {
            revision: 3,
            due_at: '2026-02-19T09:00:00Z',
            finished_at: lastSuccess,
            status: 'succeeded',
            detail: '',
            output_count: 2,
        },
    ],
}

const meta: Meta<typeof RefreshDetails> = {
    title: 'Scenes-App/Notebooks/Scheduled refresh',
    component: RefreshDetails,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const Editor: StoryObj<typeof RefreshDetails> = {
    render: function Editor() {
        const [status, setStatus] = useState(initial)
        return (
            <main className="p-4">
                <h2>Activation checks</h2>
                <RefreshDetails
                    status={status}
                    busy={false}
                    onReload={() => {}}
                    onSave={(settings) =>
                        setStatus({
                            ...status,
                            ...settings,
                            stale: (settings.freshness_minutes ?? status.freshness_minutes ?? 90) < 120,
                        })
                    }
                />
            </main>
        )
    },
}

export const Reader: StoryObj<typeof RefreshDetails> = {
    args: { status: initial, busy: false, onReload: () => {} },
}
