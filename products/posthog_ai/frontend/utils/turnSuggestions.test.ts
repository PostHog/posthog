import { dayjs } from 'lib/dayjs'

import type { TurnSuggestion } from '../types/streamTypes'
import {
    buildAlertCreatePayload,
    buildAlertDestinationPayload,
    buildErrorAlertHogFunctionPayload,
    buildScoutCreatePayload,
    buildSubscriptionCreatePayload,
    nextSubscriptionStart,
    parseTurnSuggestionParams,
} from './turnSuggestions'

const BASE = {
    turnIndex: 0,
    intent: 'metric_state',
    confidence: 0.9,
    title: 'Get this every week in Slack',
    description: 'A scout can rerun this count each week.',
}

const SCOUT = {
    mode: 'report',
    displayName: 'Weekly signups',
    description: 'Counts signed_up events for the last 7 days.',
    body: '# Weekly signups\n\nQuery signed_up for the last 7 days.',
    cadence: 'weekly',
}

const INSIGHT = { insightShortId: 'abc123', insightId: 42, insightName: 'Signups', queryKind: 'TrendsQuery' }

const FRAMES: Record<TurnSuggestion['kind'], Record<string, unknown>> = {
    scout: { ...BASE, kind: 'scout', scout: SCOUT },
    notebook: {
        ...BASE,
        kind: 'notebook',
        notebook: {
            template: 'incident',
            title: 'Why signups dropped on Tuesday',
            summary: 'A checkout error was the cause.',
            incident: { timeline: '- 14:10 release', cause: 'Checkout error.', fix: 'Rolled back.' },
        },
    },
    alert: { ...BASE, kind: 'alert', alert: { ...INSIGHT, direction: 'decrease', changePercent: 20.4 } },
    subscription: { ...BASE, kind: 'subscription', subscription: { ...INSIGHT, cadence: 'weekly' } },
    error_alert: { ...BASE, kind: 'error_alert', errorAlert: { issueId: 'issue-1', issueName: 'Checkout error' } },
}

function parsed<K extends TurnSuggestion['kind']>(kind: K): Extract<TurnSuggestion, { kind: K }> {
    const suggestion = parseTurnSuggestionParams(FRAMES[kind])
    if (suggestion?.kind !== kind) {
        throw new Error(`expected a ${kind} suggestion`)
    }
    return suggestion as Extract<TurnSuggestion, { kind: K }>
}

const SLACK = { slackIntegrationId: 7, slackChannel: 'C123|#growth' }

describe('turnSuggestions', () => {
    test.each([
        ['an unknown kind', { ...FRAMES.scout, kind: 'dashboard' }],
        ['a notebook without a title', { ...FRAMES.notebook, notebook: { title: ' ', summary: 'x' } }],
        ['a missing turn index', { ...FRAMES.scout, turnIndex: undefined }],
        ['an empty scout prompt', { ...FRAMES.scout, scout: { ...SCOUT, body: '   ' } }],
        ['an unknown cadence', { ...FRAMES.scout, scout: { ...SCOUT, cadence: 'hourly' } }],
        ['an alert without an insight', { ...FRAMES.alert, alert: { direction: 'decrease', changePercent: 20 } }],
        ['an alert with an unknown direction', { ...FRAMES.alert, alert: { ...INSIGHT, direction: 'either' } }],
        ['a subscription without a cadence', { ...FRAMES.subscription, subscription: INSIGHT }],
        ['an error alert without an issue', { ...FRAMES.error_alert, errorAlert: { issueName: 'x' } }],
        ['a non-object frame', 'scout'],
    ])('parseTurnSuggestionParams drops a frame with %s', (_label, params) => {
        expect(parseTurnSuggestionParams(params)).toBeNull()
    })

    test.each<[TurnSuggestion['kind'], Record<string, unknown>]>([
        ['scout', { scout: SCOUT }],
        [
            'notebook',
            {
                notebook: {
                    template: 'incident',
                    title: 'Why signups dropped on Tuesday',
                    summary: 'A checkout error was the cause.',
                    incident: { timeline: '- 14:10 release', cause: 'Checkout error.', fix: 'Rolled back.' },
                },
            },
        ],
        ['alert', { alert: { ...INSIGHT, direction: 'decrease', changePercent: 20 } }],
        ['subscription', { subscription: { ...INSIGHT, cadence: 'weekly' } }],
        ['error_alert', { errorAlert: { issueId: 'issue-1', issueName: 'Checkout error' } }],
    ])('parseTurnSuggestionParams keeps a %s frame with its draft', (kind, draft) => {
        expect(parseTurnSuggestionParams(FRAMES[kind])).toEqual({ ...BASE, kind, ...draft })
    })

    it('parseTurnSuggestionParams fills in the card copy, the scout mode and the notebook template', () => {
        expect(
            parseTurnSuggestionParams({
                ...FRAMES.scout,
                title: '',
                description: undefined,
                scout: { ...SCOUT, mode: undefined },
            })
        ).toMatchObject({
            title: 'Turn this into a scout',
            description: 'Run this analysis on a schedule and post the results to Slack.',
            scout: { mode: 'report' },
        })
        expect(
            parseTurnSuggestionParams({
                ...FRAMES.notebook,
                notebook: { template: 'incident', title: 'Why', summary: '', incident: { timeline: '', cause: '' } },
            })
        ).toMatchObject({ notebook: { template: 'conversation', incident: null } })
    })

    it('buildScoutCreatePayload maps the cadence to a cron and keeps a watch scout off the inactivity sweep', () => {
        const suggestion = parsed('scout')

        expect(buildScoutCreatePayload({ suggestion, cadence: 'daily', ...SLACK })).toEqual({
            display_name: 'Weekly signups',
            description: 'Counts signed_up events for the last 7 days.',
            body: SCOUT.body,
            config: {
                run_cron_schedule: '0 9 * * *',
                output_destinations: { slack: { integration_id: 7, channel: 'C123|#growth' } },
            },
        })
        const watch = { ...suggestion, scout: { ...suggestion.scout, mode: 'watch' as const } }
        expect(buildScoutCreatePayload({ suggestion: watch, cadence: 'daily', ...SLACK }).config).toMatchObject({
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
            config: { type: 'TrendsAlertConfig', series_index: 0 },
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
        const payload = buildErrorAlertHogFunctionPayload({ suggestion: parsed('error_alert'), ...SLACK })

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
            inputs: { slack_workspace: { value: 7 }, channel: { value: 'C123' } },
        })
        expect(payload.inputs?.blocks).toBeTruthy()
    })
})
