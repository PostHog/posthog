import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { dataRetentionBannerLogic } from './dataRetentionBannerLogic'

const RETENTION = {
    retention_months: 84,
    retained_from: '2019-09-22',
    docs_url: 'https://posthog.com/docs/data/events-retention',
    project_retention_months: null,
    organization_retention_months: null,
    plan_retention_months: 84,
    min_retention_months: 1,
    max_retention_months: 84,
}

describe('dataRetentionBannerLogic', () => {
    it.each([
        {
            name: 'reads the window from the events retention endpoint',
            response: [200, RETENTION],
            retentionMonths: 84,
            actionLabel: null,
        },
        {
            name: 'offers an upgrade below the longest plan',
            response: [200, { ...RETENTION, retention_months: 12, plan_retention_months: 12 }],
            retentionMonths: 12,
            actionLabel: 'Upgrade plan',
        },
        {
            name: 'links to settings when a setting shortens the window',
            response: [200, { ...RETENTION, retention_months: 12, organization_retention_months: 12 }],
            retentionMonths: 12,
            actionLabel: 'Change retention',
        },
        {
            name: 'treats a null window as retention not enforced',
            response: [200, { ...RETENTION, retention_months: null, retained_from: null }],
            retentionMonths: null,
            actionLabel: null,
        },
        {
            name: 'treats an empty response as retention not enforced',
            response: [204],
            retentionMonths: null,
            actionLabel: null,
        },
    ])('$name', async ({ response, retentionMonths, actionLabel }) => {
        useMocks({ get: { '/api/projects/:team_id/events_retention/': () => response } })
        initKeaTests()
        const logic = dataRetentionBannerLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadRetentionMonths', 'loadRetentionMonthsSuccess'])
            .toMatchValues({ retentionMonths, retentionEnforced: retentionMonths !== null })
        expect(logic.values.retentionBannerAction?.children ?? null).toEqual(actionLabel)
    })

    it('waits for the team id before loading', async () => {
        const requestedTeamIds: string[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/events_retention/': ({ params }) => {
                    requestedTeamIds.push(String(params.team_id))
                    return [200, RETENTION]
                },
            },
        })
        initKeaTests(true, null as unknown as TeamType)
        const logic = dataRetentionBannerLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions([teamLogic.actionTypes.loadCurrentTeamSuccess, 'loadRetentionMonthsSuccess'])
            .toMatchValues({ retentionMonths: 84 })
        expect(requestedTeamIds).toEqual([String(MOCK_DEFAULT_TEAM.id)])
    })

    it('does not call the endpoint in a shared view', async () => {
        let requested = false
        useMocks({
            get: {
                '/api/projects/:team_id/events_retention/': () => {
                    requested = true
                    return [200, RETENTION]
                },
            },
        })
        initKeaTests()
        ;(window as { POSTHOG_EXPORTED_DATA?: unknown }).POSTHOG_EXPORTED_DATA = { type: 'embed' }
        const logic = dataRetentionBannerLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadRetentionMonths', 'loadRetentionMonthsSuccess'])
            .toMatchValues({ retentionMonths: null })
        expect(requested).toBe(false)
        delete (window as { POSTHOG_EXPORTED_DATA?: unknown }).POSTHOG_EXPORTED_DATA
    })
})
