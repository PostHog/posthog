import type { HogFlowMinimalApi } from 'products/workflows/frontend/generated/api.schemas'

import type { LoopDTOApi } from '../generated/api.schemas'
import { spaceLoopsFromHogFlows, spaceLoopsFromLoops } from './spaceLoops'

function hogFlow(
    id: string,
    spaceInput: string | null,
    trigger: Record<string, unknown>,
    extra = {}
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
                    inputs: spaceInput === null ? {} : { channel: { value: spaceInput } },
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
})
