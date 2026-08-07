import { render } from '@testing-library/react'

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

const change = (field: string, before: ActivityChange['before'], after: ActivityChange['after']): ActivityChange => ({
    type: ActivityScope.SIGNAL_TEAM_CONFIG,
    action: 'changed',
    field,
    before,
    after,
})

const renderDescription = (changes: ActivityChange[]): { text: string; container: HTMLElement } => {
    const { description } = signalTeamConfigActivityDescriber(logItem(changes))
    const { container } = render(description as JSX.Element)
    return { text: container.textContent || '', container }
}

describe('signalTeamConfigActivityDescriber', () => {
    // The stored values are P4/P1, but the control labels them All/P1+, so the entry has to name the
    // option the user actually picked.
    it('names both ends of a threshold change with the labels the control shows', () => {
        const { text } = renderDescription([change('default_autostart_priority', 'P4', 'P1')])
        expect(text).toBe('Ada changed the PR generation threshold from All to P1+')
    })

    it('masks the actor so a name or email cannot reach autocapture or session replay', () => {
        const { container } = renderDescription([change('default_autostart_priority', 'P4', 'P1')])
        expect(container.querySelector('.ph-no-capture')?.textContent).toBe('Ada')
    })

    it('masks the Slack channel name, which belongs to the customer', () => {
        const { text, container } = renderDescription([
            change('default_slack_notification_channel', null, 'C123|#customer-escalation'),
        ])
        expect(text).toBe('Ada set the default Slack channel for inbox notifications to #customer-escalation')
        expect([...container.querySelectorAll('.ph-no-capture')].map((el) => el.textContent)).toEqual([
            'Ada',
            '#customer-escalation',
        ])
    })

    // The null rows are the ones worth guarding: a team that never set the switch had PR generation
    // on, so null to false is an opt-out, while null to true leaves the setting where it was.
    it.each([
        ['turned off PR generation for inbox reports', true, false],
        ['turned off PR generation for inbox reports', null, false],
        ['turned on PR generation for inbox reports', false, true],
        ["updated the team's inbox settings", null, true],
    ])('reads "%s" from an autostart_enabled change of %s to %s', (sentence, before, after) => {
        const { text } = renderDescription([change('autostart_enabled', before, after)])
        expect(text).toBe(`Ada ${sentence}`)
    })

    it('falls back to one line when several settings change at once', () => {
        const { text } = renderDescription([
            change('autostart_enabled', false, true),
            change('default_autostart_priority', 'P4', 'P2'),
        ])
        expect(text).toBe("Ada updated the team's inbox settings")
    })
})
