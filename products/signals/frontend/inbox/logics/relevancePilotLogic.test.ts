/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReportStatus } from '../types'
import { relevancePilotLogic } from './relevancePilotLogic'

const report = {
    id: 'example-report',
    title: 'Example',
    summary: '',
    status: SignalReportStatus.READY,
    priority: 'P1',
    actionability: 'immediately_actionable',
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    signal_count: 1,
    total_weight: 1,
    artefact_count: 1,
    is_suggested_reviewer: true,
}

it('refreshes the shortlist after personal Not now and undo without writing shared report state', async () => {
    let hidden = false
    useMocks({
        get: {
            '/api/projects/:team_id/signals/reports/available_reviewers/': () => [200, {}],
            '/api/projects/:team_id/signals/reports/': () => [
                200,
                { results: hidden ? [] : [report], count: hidden ? 0 : 1 },
            ],
        },
        post: {
            '/api/projects/:team_id/signals/reports/:id/snooze/': async ({ request }) => {
                hidden = ((await request.json()) as { snoozed: boolean }).snoozed
                return [200, { snoozed_until: hidden ? '2026-10-01T00:00:00Z' : null }]
            },
        },
    })
    initKeaTests()
    const logic = relevancePilotLogic()
    await expectLogic(logic, () => {
        logic.mount()
    }).toDispatchActions(['loadReportsSuccess'])
    const loaded = logic.values.reports[0]
    await expectLogic(logic, () => logic.actions.snooze(loaded, true))
        .toDispatchActions(['snoozeSuccess', 'loadReportsSuccess'])
        .toMatchValues({ reports: [], lastSnoozed: loaded })
    await expectLogic(logic, () => logic.actions.snooze(loaded, false))
        .toDispatchActions(['snoozeSuccess', 'loadReportsSuccess'])
        .toMatchValues({ lastSnoozed: null })
    expect(logic.values.reports).toHaveLength(1)
    logic.unmount()
})
