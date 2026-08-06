import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { signalTeamConfigActivityDescriber } from './activityDescriber'

const logItem = (changes: ActivityChange[]): ActivityLogItem => ({
    activity: 'updated',
    created_at: '2026-06-25T10:00:00Z',
    scope: ActivityScope.SIGNAL_TEAM_CONFIG,
    item_id: 'config-uuid',
    user: { first_name: 'Ada', email: 'ada@posthog.com' },
    detail: { merge: null, trigger: null, changes, name: 'inbox settings' },
})

const change = (field: string, before: unknown, after: unknown): ActivityChange => ({
    type: ActivityScope.SIGNAL_TEAM_CONFIG,
    action: 'changed',
    field,
    before,
    after,
})

describe('signalTeamConfigActivityDescriber', () => {
    it('names both ends of a threshold change, which is the point of logging it', () => {
        const { description } = signalTeamConfigActivityDescriber(
            logItem([change('default_autostart_priority', 'P4', 'P1')])
        )
        expect(description).toBe('Ada changed the PR generation threshold from P4 to P1')
    })

    // The null row is the one worth guarding: a team that never set the switch had PR generation
    // on, so null to false is an opt-out, not a first-time enable.
    it.each([
        ['turned off', true, false],
        ['turned off', null, false],
        ['turned on', false, true],
    ])('reads %s from an autostart_enabled change of %s to %s', (verb, before, after) => {
        const { description } = signalTeamConfigActivityDescriber(
            logItem([change('autostart_enabled', before, after)])
        )
        expect(description).toBe(`Ada ${verb} PR generation for inbox reports`)
    })

    it('falls back to one line when several settings change at once', () => {
        const { description } = signalTeamConfigActivityDescriber(
            logItem([change('autostart_enabled', false, true), change('default_autostart_priority', 'P4', 'P2')])
        )
        expect(description).toBe("Ada updated the team's inbox settings")
    })
})
