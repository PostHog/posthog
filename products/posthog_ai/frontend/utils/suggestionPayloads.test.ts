import { dayjs } from 'lib/dayjs'

import type { TurnSuggestion } from '../types/streamTypes'
import {
    buildAlertCreatePayload,
    buildAlertDestinationPayload,
    buildErrorAlertHogFunctionPayload,
    buildScoutCreatePayload,
    buildSubscriptionCreatePayload,
    nextSubscriptionStart,
} from './suggestionPayloads'
import { SUGGESTION_FRAMES } from './turnSuggestionFixtures'
import { parseTurnSuggestionParams } from './turnSuggestions'

function parsed<K extends TurnSuggestion['kind']>(kind: K): Extract<TurnSuggestion, { kind: K }> {
    const suggestion = parseTurnSuggestionParams(SUGGESTION_FRAMES[kind])
    if (suggestion?.kind !== kind) {
        throw new Error(`expected a ${kind} suggestion`)
    }
    return suggestion as Extract<TurnSuggestion, { kind: K }>
}

const SLACK = { slackIntegrationId: 7, slackChannel: 'C123|#growth' }

describe('suggestionPayloads', () => {
    it('buildScoutCreatePayload maps the cadence to a cron and keeps a watch scout off the inactivity sweep', () => {
        const suggestion = parsed('scout')

        expect(buildScoutCreatePayload({ suggestion, cadence: 'daily', body: 'Edited steps', ...SLACK })).toEqual({
            display_name: 'Weekly signups',
            description: 'Counts signed_up events for the last 7 days.',
            body: 'Edited steps',
            config: {
                run_cron_schedule: '0 9 * * *',
                output_destinations: { slack: { integration_id: 7, channel: 'C123|#growth' } },
            },
        })
        const watch = { ...suggestion, scout: { ...suggestion.scout, mode: 'watch' as const } }
        expect(
            buildScoutCreatePayload({ suggestion: watch, cadence: 'daily', body: '', ...SLACK }).config
        ).toMatchObject({
            auto_pause_exempt: true,
        })
    })

    it('buildAlertCreatePayload turns the percent into a relative bound on the first series', () => {
        expect(
            buildAlertCreatePayload({
                suggestion: parsed('alert'),
                direction: 'increase',
                changePercent: 35,
                insightId: 42,
                userId: 9,
            })
        ).toEqual({
            insight: 42,
            subscribed_users: [9],
            name: 'Signups: 35% increase',
            enabled: true,
            condition: { type: 'relative_increase' },
            config: { type: 'TrendsAlertConfig', series_index: 0, check_ongoing_interval: false },
            threshold: { configuration: { type: 'percentage', bounds: { upper: 0.35 } } },
            calculation_interval: 'daily',
        })
    })

    test.each([
        ['a picker value', 'C123|#growth', { slack_channel_id: 'C123', slack_channel_name: 'growth' }],
        ['a bare channel id', 'C123', { slack_channel_id: 'C123', slack_channel_name: undefined }],
    ])('buildAlertDestinationPayload splits %s', (_label, slackChannel, expected) => {
        expect(buildAlertDestinationPayload({ slackIntegrationId: 7, slackChannel })).toEqual({
            type: 'slack',
            slack_workspace_id: 7,
            ...expected,
        })
    })

    test.each([
        ['daily before 9', 'daily', '2026-09-16T07:30:00', '2026-09-16 09:00'],
        ['daily after 9', 'daily', '2026-09-16T10:00:00', '2026-09-17 09:00'],
        ['weekly on a Wednesday', 'weekly', '2026-09-16T10:00:00', '2026-09-21 09:00'],
        ['weekly on a Monday morning', 'weekly', '2026-09-21T08:00:00', '2026-09-21 09:00'],
    ] as const)('nextSubscriptionStart picks the next 9:00 for %s', (_label, cadence, now, expected) => {
        expect(nextSubscriptionStart(cadence, dayjs(now)).format('YYYY-MM-DD HH:mm')).toBe(expected)
    })

    it('buildSubscriptionCreatePayload sends the insight to the channel on Mondays without a test delivery', () => {
        const now = dayjs('2026-09-16T10:00:00')

        expect(
            buildSubscriptionCreatePayload({
                suggestion: parsed('subscription'),
                cadence: 'weekly',
                insightId: 42,
                now,
                ...SLACK,
            })
        ).toEqual({
            insight: 42,
            title: 'Weekly report: Signups',
            target_type: 'slack',
            integration_id: 7,
            target_value: 'C123|#growth',
            frequency: 'weekly',
            interval: 1,
            byweekday: ['monday'],
            start_date: nextSubscriptionStart('weekly', now).toISOString(),
            send_test_now: false,
        })
    })

    it('buildErrorAlertHogFunctionPayload scopes the Slack reopened template to the one issue', () => {
        const payload = buildErrorAlertHogFunctionPayload({
            suggestion: parsed('error_alert'),
            ...SLACK,
            inputsSchema: [
                { key: 'icon_emoji', type: 'string', label: 'Emoji icon', default: ':hedgehog:' },
                { key: 'channel', type: 'string', label: 'Channel', default: 'C-default' },
            ],
        })

        expect(payload).toMatchObject({
            type: 'internal_destination',
            template_id: 'template-slack',
            name: 'Post to Slack on issue reopened: #growth',
            enabled: true,
            filters: {
                source: 'internal-events',
                events: [{ id: '$error_tracking_issue_reopened', type: 'events' }],
                properties: [{ key: '$exception_issue_id', value: 'issue-1', operator: 'exact', type: 'event' }],
            },
            inputs: { icon_emoji: { value: ':hedgehog:' }, slack_workspace: { value: 7 }, channel: { value: 'C123' } },
        })
        expect(payload.inputs?.blocks).toBeTruthy()
    })
})
