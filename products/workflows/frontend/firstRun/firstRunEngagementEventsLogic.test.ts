import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { firstRunEngagementEventsLogic } from './firstRunEngagementEventsLogic'

describe('firstRunEngagementEventsLogic', () => {
    let logic: ReturnType<typeof firstRunEngagementEventsLogic.build>
    let teamUpdates: Record<string, any>[]

    beforeEach(() => {
        teamUpdates = []
        useMocks({
            patch: {
                '/api/projects/:team_id/': async ({ request }) => {
                    const update = (await request.json()) as Record<string, any>
                    teamUpdates.push(update)
                    return [200, { ...MOCK_DEFAULT_TEAM, ...update }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: true })
    })

    afterEach(() => {
        logic?.unmount()
    })

    function mountWithTeam(team: Partial<TeamType>): void {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ...team })
        logic = firstRunEngagementEventsLogic()
        logic.mount()
    }

    async function enableAndSettle(): Promise<void> {
        logic.actions.enableEngagementEvents()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(teamLogic).toFinishAllListeners()
    }

    it.each([true, false])('offers the action only while first run is enabled=%s', async (enabled) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: enabled })
        mountWithTeam({ workflows_config: { capture_workflows_engagement_events: false } })
        expect(logic.values.offerEngagementEvents).toBe(enabled)

        await enableAndSettle()

        expect(teamUpdates).toEqual(
            enabled ? [{ workflows_config: { capture_workflows_engagement_events: true } }] : []
        )
        expect(logic.values).toMatchObject({ engagementEventsCaptured: enabled, offerEngagementEvents: false })
    })

    it.each([
        {
            who: 'a member',
            team: {
                effective_membership_level: OrganizationMembershipLevel.Member,
                workflows_config: { capture_workflows_engagement_events: false },
            },
        },
        {
            who: 'an admin whose setting is on',
            team: { workflows_config: { capture_workflows_engagement_events: true } },
        },
    ])('does not offer the action to $who and sends no update', async ({ team }) => {
        mountWithTeam(team)
        expect(logic.values.offerEngagementEvents).toBe(false)

        await enableAndSettle()

        expect(teamUpdates).toEqual([])
    })
})
