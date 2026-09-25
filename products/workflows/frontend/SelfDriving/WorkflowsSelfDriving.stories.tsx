import { Meta, StoryFn } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { SignalReportListApi, SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { WorkflowsSelfDriving } from './WorkflowsSelfDriving'

const configsEndpoint = '/api/projects/:team_id/signals/scout/configs/'
const syncEndpoint = '/api/projects/:team_id/signals/scout/configs/sync/'
const reportsEndpoint = '/api/projects/:team_id/signals/reports/'

const meta: Meta<typeof WorkflowsSelfDriving> = {
    title: 'Products/Workflows/Self-driving',
    component: WorkflowsSelfDriving,
    parameters: {
        layout: 'padded',
        testOptions: { waitForLoadersToDisappear: true },
        mockDate: '2026-09-24T09:00:00Z',
    },
}
export default meta

function scoutConfig(enabled: boolean): SignalScoutConfigApi {
    return {
        id: '0199c0de-0000-7000-8000-00000000000a',
        skill_name: 'signals-scout-workflows-fatigue',
        display_name: 'Workflows audience fatigue',
        description: 'Finds email workflows whose audiences overlap and whose sends land close together.',
        scout_origin: 'canonical',
        scout_role: 'specialist',
        enabled,
        status: enabled ? 'active' : 'paused_by_user',
        pause_reason: null,
        emit: true,
        run_interval_minutes: 1440,
        run_cron_schedule: '0 7 * * *',
        last_run_at: enabled ? '2026-09-24T07:02:00Z' : null,
        tags: ['workflows'],
        created_at: '2026-09-20T10:00:00Z',
        updated_at: '2026-09-24T07:02:00Z',
    } as SignalScoutConfigApi
}

const suggestions = [
    {
        id: '0199c0de-0000-7000-8000-000000000101',
        title: '3 workflows reach mostly the same people within 48 hours',
        summary:
            'The **Monthly product update**, the **Release notes digest** and the **Feature spotlight** target audiences that overlap by 92 percent, and all three send between Tuesday and Thursday. Move the spotlight to the following Monday, or exclude the update cohort from it.',
        status: 'pending_input',
        priority: 'P2',
        created_at: '2026-09-24T07:05:00Z',
        updated_at: '2026-09-24T07:05:00Z',
    },
    {
        id: '0199c0de-0000-7000-8000-000000000102',
        title: 'Two onboarding sequences email new signups on the same days',
        summary:
            'The **Welcome series** and the **Getting started tips** both send on days 1, 3 and 7 after signup, so every new signup gets two emails on each of those days. Shift the tips to days 2, 4 and 8.',
        status: 'ready',
        priority: 'P3',
        created_at: '2026-09-22T07:05:00Z',
        updated_at: '2026-09-23T07:04:00Z',
    },
] as SignalReportListApi[]

export const OptIn: StoryFn = () => {
    useStorybookMocks({
        get: { [configsEndpoint]: [scoutConfig(false)], [reportsEndpoint]: { count: 0, results: [] } },
        post: { [syncEndpoint]: [] },
    })
    return <WorkflowsSelfDriving />
}

export const Enabled: StoryFn = () => {
    useStorybookMocks({
        get: {
            [configsEndpoint]: [scoutConfig(true)],
            [reportsEndpoint]: { count: suggestions.length, results: suggestions },
        },
        post: { [syncEndpoint]: [] },
    })
    return <WorkflowsSelfDriving />
}

export const EnabledWithoutSuggestions: StoryFn = () => {
    useStorybookMocks({
        get: { [configsEndpoint]: [scoutConfig(true)], [reportsEndpoint]: { count: 0, results: [] } },
        post: { [syncEndpoint]: [] },
    })
    return <WorkflowsSelfDriving />
}

export const Unavailable: StoryFn = () => {
    useStorybookMocks({
        get: { [configsEndpoint]: [], [reportsEndpoint]: { count: 0, results: [] } },
        post: { [syncEndpoint]: [] },
    })
    return <WorkflowsSelfDriving />
}
