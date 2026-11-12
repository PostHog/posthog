import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { dataRetentionBannerLogic } from './dataRetentionBannerLogic'

const RETENTION = {
    retention_months: null,
    retained_from: null,
    docs_url: 'https://posthog.com/docs/data/events-retention',
    project_retention_months: null,
    organization_retention_months: null,
    default_retention_months: 24,
    plan_retention_months: 84,
    min_retention_months: 1,
    max_retention_months: 84,
    retention_months_choices: [1, 3, 12, 24, 36, 60, 84],
}

describe('dataRetentionBannerLogic', () => {
    it.each([
        {
            name: 'names the default period when nothing is set',
            response: [200, RETENTION],
            periodLabel: '2-year',
        },
        {
            name: 'names the organization period over the default',
            response: [200, { ...RETENTION, organization_retention_months: 12 }],
            periodLabel: '1-year',
        },
        {
            name: 'names the project period over the organization one',
            response: [200, { ...RETENTION, project_retention_months: 36, organization_retention_months: 12 }],
            periodLabel: '3-year',
        },
        {
            name: 'caps the period at the plan',
            response: [
                200,
                {
                    ...RETENTION,
                    organization_retention_months: 84,
                    plan_retention_months: 12,
                    default_retention_months: 12,
                },
            ],
            periodLabel: '1-year',
        },
        {
            name: 'has no period for an empty response',
            response: [204],
            periodLabel: null,
        },
    ])('$name', async ({ response, periodLabel }) => {
        useMocks({ get: { '/api/projects/:team_id/events_retention/': () => response } })
        initKeaTests()
        const logic = dataRetentionBannerLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadRetention', 'loadRetentionSuccess'])
        expect(logic.values.retentionPeriodLabel).toEqual(periodLabel)
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
            .toDispatchActions([teamLogic.actionTypes.loadCurrentTeamSuccess, 'loadRetentionSuccess'])
            .toMatchValues({ retentionPeriodLabel: '2-year' })
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
            .toDispatchActions(['loadRetention', 'loadRetentionSuccess'])
            .toMatchValues({ retention: null })
        expect(requested).toBe(false)
        delete (window as { POSTHOG_EXPORTED_DATA?: unknown }).POSTHOG_EXPORTED_DATA
    })
})
