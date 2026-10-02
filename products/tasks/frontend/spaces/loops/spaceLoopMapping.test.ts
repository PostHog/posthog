import type { HogFlowMinimalApi } from 'products/workflows/frontend/generated/api.schemas'

import type { LoopDTOApi } from '../../generated/api.schemas'
import {
    spaceLoopFromHogFlow,
    spaceLoopFromLoop,
    spaceLoopsFromHogFlows,
    spaceLoopsFromLoops,
} from './spaceLoopMapping'

function hogFlow(
    id: string,
    spaceInput: string | null,
    trigger: Record<string, unknown>,
    extra = {},
    taskInputs: Record<string, unknown> = {}
): HogFlowMinimalApi {
    return {
        id,
        name: id,
        description: '',
        status: 'active',
        last_run: null,
        actions: [
            { id: 'trigger', type: 'trigger', config: trigger },
            {
                id: 'create_task',
                type: 'function',
                config: {
                    template_id: 'template-posthog-create-task',
                    inputs: spaceInput === null ? taskInputs : { channel: { value: spaceInput }, ...taskInputs },
                },
            },
            { id: 'exit', type: 'exit', config: {} },
        ],
        ...extra,
    } as unknown as HogFlowMinimalApi
}

function loop(id: string, spaceId: string | null, extra: Partial<LoopDTOApi> = {}): LoopDTOApi {
    return {
        id,
        name: id,
        description: '',
        enabled: true,
        disabled_reason: null,
        context_target: spaceId ? { channel_id: spaceId, name: 'Checkout' } : null,
        last_run_at: null,
        last_run_status: null,
        consecutive_failures: 0,
        triggers: [],
        instructions: '',
        model: '',
        reasoning_effort: null,
        repositories: [],
        notifications: { push: {}, email: {}, slack: {} },
        ...extra,
    } as unknown as LoopDTOApi
}

const githubTrigger = {
    type: 'internal-event',
    filters: { events: [{ id: '$github_event_received', type: 'events' }] },
}
const slackTrigger = {
    type: 'internal-event',
    filters: { events: [{ id: '$slack_message_received', type: 'events' }] },
}

describe('spaceLoops', () => {
    it('keeps only the workflows whose task step files runs in the space, and labels their triggers', () => {
        const flows = [
            hogFlow('schedule', 'space-a|Checkout', { type: 'schedule' }),
            hogFlow('github', 'space-a', githubTrigger),
            hogFlow('slack', 'space-a|Name|with pipes', slackTrigger),
            hogFlow('event', 'space-a|Checkout', { type: 'event' }),
            hogFlow('other-space', 'space-b|Billing', { type: 'schedule' }),
            hogFlow('no-space', null, { type: 'schedule' }),
            hogFlow('archived', 'space-a|Checkout', { type: 'schedule' }, { status: 'archived' }),
        ]

        expect(spaceLoopsFromHogFlows(flows, 'space-a').map(({ id, trigger }) => [id, trigger])).toEqual([
            ['schedule', 'Schedule'],
            ['github', 'GitHub event'],
            ['slack', 'Slack message'],
            ['event', 'PostHog event'],
        ])
    })

    it.each([
        ['an active loop', {}, 'Active'],
        ['a loop someone paused', { enabled: false }, 'Paused'],
        [
            'a loop paused by the usage limit',
            { enabled: false, disabled_reason: 'usage_limited' },
            'Paused: usage limit',
        ],
        ['a loop whose runs keep failing', { consecutive_failures: 2 }, 'Failing'],
    ])('labels %s', (_, extra, label) => {
        const rows = spaceLoopsFromLoops(
            [loop('a', 'space-a', extra), loop('b', 'space-b'), loop('c', null)],
            'space-a'
        )
        expect(rows.map((row) => [row.id, row.status.label])).toEqual([['a', label]])
    })

    it.each([
        [
            'a weekday workflow schedule',
            spaceLoopFromHogFlow({
                ...hogFlow('a', 'space-a', { type: 'schedule' }),
                schedules: [
                    {
                        rrule: 'FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,TU,WE,TH,FR',
                        starts_at: '2026-10-05T16:00:00Z',
                        timezone: 'America/Los_Angeles',
                    },
                ],
            } as unknown as HogFlowMinimalApi),
            'Weekdays at 9:00 AM PDT',
        ],
        [
            'an every-other-day workflow schedule that ends',
            spaceLoopFromHogFlow({
                ...hogFlow('a', 'space-a', { type: 'schedule' }),
                schedules: [{ rrule: 'FREQ=DAILY;INTERVAL=2;COUNT=5', starts_at: '2026-10-05T16:00:00Z' }],
            } as unknown as HogFlowMinimalApi),
            'Custom schedule · FREQ=DAILY;INTERVAL=2;COUNT=5',
        ],
        [
            'a workflow schedule on two days of the month',
            spaceLoopFromHogFlow({
                ...hogFlow('a', 'space-a', { type: 'schedule' }),
                schedules: [{ rrule: 'FREQ=MONTHLY;BYMONTHDAY=15,30', starts_at: '2026-10-15T16:00:00Z' }],
            } as unknown as HogFlowMinimalApi),
            'Custom schedule · FREQ=MONTHLY;BYMONTHDAY=15,30',
        ],
        [
            'a workflow schedule with no schedule row',
            spaceLoopFromHogFlow({ ...hogFlow('a', 'space-a', { type: 'schedule' }), schedules: [] }),
            'No schedule set',
        ],
        [
            'a Monday cron schedule',
            spaceLoopFromLoop(
                loop('a', 'space-a', {
                    triggers: [
                        {
                            type: 'schedule',
                            enabled: true,
                            config: { cron_expression: '30 11 * * 1', timezone: 'Europe/Prague' },
                        },
                    ],
                } as unknown as Partial<LoopDTOApi>)
            ),
            'Mondays at 11:30 AM (Europe/Prague)',
        ],
        [
            'a paused GitHub trigger',
            spaceLoopFromLoop(
                loop('a', 'space-a', {
                    triggers: [
                        {
                            type: 'github',
                            enabled: false,
                            config: { repository: 'example/repo', events: ['pull_request'] },
                        },
                    ],
                } as unknown as Partial<LoopDTOApi>)
            ),
            'GitHub · example/repo (pull_request) (disabled)',
        ],
    ])('describes %s', (_, spaceLoop, trigger) => {
        expect(spaceLoop.triggers).toEqual([trigger])
    })

    it.each([
        ['an active schedule workflow', hogFlow('a', 'space-a', { type: 'schedule' }), 'Active', true, []],
        ['a manual workflow', hogFlow('a', 'space-a', { type: 'manual' }), 'Active', false, []],
        [
            'an archived schedule workflow',
            hogFlow('a', 'space-a', { type: 'schedule' }, { status: 'archived' }),
            'Archived',
            false,
            [],
        ],
        [
            'a Slack workflow with the thread reply left at its default',
            hogFlow('a', 'space-a', slackTrigger),
            'Active',
            false,
            ['Slack thread reply'],
        ],
        [
            'a schedule workflow with the thread reply input on',
            hogFlow('a', 'space-a', { type: 'schedule' }, {}, { reply_in_slack_thread: { value: true } }),
            'Active',
            true,
            [],
        ],
    ])('maps %s', (_, flow, statusLabel, canRunNow, notifications) => {
        expect(spaceLoopFromHogFlow(flow)).toMatchObject({ status: { label: statusLabel }, canRunNow, notifications })
    })
})
