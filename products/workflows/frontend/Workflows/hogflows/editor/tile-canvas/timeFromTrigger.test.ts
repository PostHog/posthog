import { getEdgeId } from '../../edgeId'
import type { HogFlow, HogFlowAction, HogFlowEdge } from '../../types'
import { labelTooltip, reachedAfterTriggerText, timeFromTrigger } from './timeFromTrigger'

type Config = Record<string, unknown>

const step = (id: string, type: HogFlowAction['type'] = 'function', config: Config = {}): HogFlowAction =>
    ({ id, type, name: id, description: '', config }) as HogFlowAction

const delay = (id: string, duration: string): HogFlowAction => step(id, 'delay', { delay_duration: duration })
const waitFor = (id: string, maxWait: string): HogFlowAction =>
    step(id, 'wait_until_condition', { condition: { filters: {} }, max_wait_duration: maxWait })
const timeWindow = (id: string, day: unknown, time: unknown): HogFlowAction =>
    step(id, 'wait_until_time_window', { timezone: 'UTC', day, time })
const untilDate = (id: string, maxDelay?: string): HogFlowAction =>
    step(id, 'delay', { delay_until: { expression: 'person.properties.trial_ends_at' }, max_delay_duration: maxDelay })

const next = (from: string, to: string): HogFlowEdge => ({ from, to, type: 'continue' })
const branch = (from: string, to: string, index = 0): HogFlowEdge => ({ from, to, type: 'branch', index })

const flow = (actions: HogFlowAction[], edges: HogFlowEdge[]): Pick<HogFlow, 'actions' | 'edges'> => ({
    actions,
    edges,
})

// trigger -> 10 day delay -> wait up to 4 days for an event; a match goes to `converted`, no match to `last_day`
const trialFlow = flow(
    [
        step('trigger', 'trigger'),
        step('welcome'),
        delay('wait_ten_days', '10d'),
        waitFor('wait_upgrade', '4d'),
        step('converted', 'exit'),
        step('last_day'),
        step('exit', 'exit'),
    ],
    [
        next('trigger', 'welcome'),
        next('welcome', 'wait_ten_days'),
        next('wait_ten_days', 'wait_upgrade'),
        branch('wait_upgrade', 'converted'),
        next('wait_upgrade', 'last_day'),
        next('last_day', 'exit'),
    ]
)

// trigger -> split; the first path waits `first`, the other `second`, and both join at `joined`
const splitFlow = (first: string, second: string): Pick<HogFlow, 'actions' | 'edges'> =>
    flow(
        [
            step('trigger', 'trigger'),
            step('split', 'conditional_branch'),
            delay('a', first),
            delay('b', second),
            step('joined'),
        ],
        [next('trigger', 'split'), branch('split', 'a'), next('split', 'b'), next('a', 'joined'), next('b', 'joined')]
    )

const chain = (...waits: HogFlowAction[]): Pick<HogFlow, 'actions' | 'edges'> => {
    const actions = [step('trigger', 'trigger'), ...waits, step('target')]
    return flow(
        actions,
        actions.slice(1).map((action, index) => next(actions[index].id, action.id))
    )
}

const stepText = (workflow: Pick<HogFlow, 'actions' | 'edges'>, id: string): string | undefined =>
    reachedAfterTriggerText(timeFromTrigger(workflow).steps.get(id))

describe('timeFromTrigger', () => {
    test.each([
        ['a step right after the trigger has no wait to show', trialFlow, 'welcome', undefined],
        [
            'fixed delays add up',
            chain(delay('a', '1d'), delay('b', '4h')),
            'target',
            'Reached 1 day 4 hours after the trigger',
        ],
        [
            'a matched wait can end at any time up to its timeout',
            trialFlow,
            'converted',
            'Reached 10 days to 14 days after the trigger',
        ],
        ['the no-match path waits for the whole timeout', trialFlow, 'last_day', 'Reached 14 days after the trigger'],
        ['a step after the no-match path keeps its time', trialFlow, 'exit', 'Reached 14 days after the trigger'],
        [
            'joined paths span the shortest and longest path',
            splitFlow('6h', '2d'),
            'joined',
            'Reached 6 hours to 2 days after the trigger',
        ],
        [
            'joined paths span them in either order',
            splitFlow('2d', '6h'),
            'joined',
            'Reached 6 hours to 2 days after the trigger',
        ],
        [
            'a match with no wait before it may come at once',
            flow(
                [step('trigger', 'trigger'), waitFor('w', '3d'), step('target')],
                [next('trigger', 'w'), branch('w', 'target')]
            ),
            'target',
            'Reached up to 3 days after the trigger',
        ],
        [
            'a delay holds to the executor ceiling of its unit',
            chain(delay('a', '48h')),
            'target',
            'Reached 1 day after the trigger',
        ],
        [
            'a wait holds to the executor ceiling of its unit',
            flow(
                [step('trigger', 'trigger'), waitFor('w', '45d'), step('target')],
                [next('trigger', 'w'), next('w', 'target')]
            ),
            'target',
            'Reached 30 days after the trigger',
        ],
        [
            'a wait with no complete timeout has no upper bound',
            flow(
                [step('trigger', 'trigger'), delay('a', '2d'), waitFor('w', 'd'), step('target')],
                [next('trigger', 'a'), next('a', 'w'), branch('w', 'target')]
            ),
            'target',
            'Reached 2 days or more after the trigger',
        ],
        [
            'a date wait lasts at most its ceiling',
            chain(untilDate('a', '7d')),
            'target',
            'Reached up to 7 days after the trigger',
        ],
        [
            'a date wait without a ceiling uses the default',
            chain(untilDate('a')),
            'target',
            'Reached up to 30 days after the trigger',
        ],
        ['a time window open at any time does not wait', chain(timeWindow('a', 'any', 'any')), 'target', undefined],
        [
            'a daily time window waits while it is closed, plus the hour a clock change can add',
            chain(timeWindow('a', 'any', ['09:00', '17:00'])),
            'target',
            'Reached up to 17 hours after the trigger',
        ],
        [
            'a time window on weekdays waits over the weekend',
            chain(timeWindow('a', 'weekday', 'any')),
            'target',
            'Reached up to 2 days 1 hour after the trigger',
        ],
        [
            'business hours wait from Friday evening to Monday morning',
            chain(timeWindow('a', 'weekday', ['09:00', '17:00'])),
            'target',
            'Reached up to 2 days 17 hours after the trigger',
        ],
        [
            'a time window on one day waits up to six days',
            chain(timeWindow('a', ['monday'], 'any')),
            'target',
            'Reached up to 6 days 1 hour after the trigger',
        ],
        [
            'a window past midnight waits through the day',
            chain(timeWindow('a', 'any', ['22:00', '06:00'])),
            'target',
            'Reached up to 17 hours after the trigger',
        ],
        [
            'a time window on every day does not wait',
            chain(
                timeWindow('a', ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], 'any')
            ),
            'target',
            undefined,
        ],
        [
            'a window that starts as it ends is always open',
            chain(timeWindow('a', 'any', ['09:00', '09:00'])),
            'target',
            undefined,
        ],
        [
            'a time window with no days has no upper bound',
            chain(delay('d', '1d'), timeWindow('a', [], 'any')),
            'target',
            'Reached 1 day or more after the trigger',
        ],
        [
            'a time window with an incomplete time range has no upper bound',
            chain(delay('d', '1d'), timeWindow('a', 'any', ['09:00'])),
            'target',
            'Reached 1 day or more after the trigger',
        ],
        [
            'a time window with no time range has no upper bound',
            chain(delay('d', '1d'), timeWindow('a', 'any', undefined)),
            'target',
            'Reached 1 day or more after the trigger',
        ],
        [
            'a time window with an hour past the end of the day has no upper bound',
            chain(delay('d', '1d'), timeWindow('a', 'any', ['26:00', '01:00'])),
            'target',
            'Reached 1 day or more after the trigger',
        ],
        [
            'a wait with no timeout continues at once',
            flow(
                [step('trigger', 'trigger'), delay('a', '2d'), waitFor('w', ''), step('target')],
                [next('trigger', 'a'), next('a', 'w'), branch('w', 'target')]
            ),
            'target',
            'Reached 2 days after the trigger',
        ],
        [
            'bounds that read the same show one time',
            flow(
                [step('trigger', 'trigger'), delay('a', '1d'), delay('b', '2h'), waitFor('w', '15m'), step('target')],
                [next('trigger', 'a'), next('a', 'b'), next('b', 'w'), branch('w', 'target')]
            ),
            'target',
            'Reached 1 day 2 hours after the trigger',
        ],
        [
            'a date wait with a cap it cannot read uses the default',
            chain(untilDate('a', 'whenever')),
            'target',
            'Reached up to 30 days after the trigger',
        ],
        [
            'a wait that its filters can skip may not wait at all',
            chain({ ...delay('a', '7d'), filters: { properties: [{ key: 'plan', value: 'free', type: 'person' }] } }),
            'target',
            'Reached up to 7 days after the trigger',
        ],
        [
            'paths from two triggers join without a loop',
            flow(
                [step('t1', 'trigger'), step('t2', 'trigger'), delay('d1', '1d'), delay('d2', '2d'), step('joined')],
                [next('t1', 'd1'), next('t2', 'd2'), next('d1', 'joined'), next('d2', 'joined')]
            ),
            'joined',
            'Reached 1 day to 2 days after the trigger',
        ],
        [
            'a tiny fraction of a second still names a time',
            chain(delay('a', '.0004s')),
            'target',
            'Reached 1 second after the trigger',
        ],
        [
            'a delay under a second still names a time',
            chain(delay('a', '.4s')),
            'target',
            'Reached 1 second after the trigger',
        ],
        [
            'a fractional delay does not gain a second from floating point',
            chain(delay('a', '4.15m')),
            'target',
            'Reached 4 minutes 9 seconds after the trigger',
        ],
        [
            'a loop back to an earlier wait has no upper bound',
            flow(
                [
                    step('trigger', 'trigger'),
                    delay('retry_delay', '1d'),
                    step('retry', 'conditional_branch'),
                    step('exit', 'exit'),
                ],
                [
                    next('trigger', 'retry_delay'),
                    next('retry_delay', 'retry'),
                    branch('retry', 'retry_delay'),
                    next('retry', 'exit'),
                ]
            ),
            'exit',
            'Reached 1 day or more after the trigger',
        ],
        [
            'a shorter path into a loop still sets the earliest time',
            flow(
                [
                    step('trigger', 'trigger'),
                    step('split', 'conditional_branch'),
                    delay('one_day', '1d'),
                    delay('ten_days', '10d'),
                    delay('retry_delay', '1d'),
                    step('retry', 'conditional_branch'),
                    step('exit', 'exit'),
                ],
                [
                    next('trigger', 'split'),
                    branch('split', 'one_day'),
                    next('split', 'ten_days'),
                    next('one_day', 'retry_delay'),
                    next('ten_days', 'retry'),
                    next('retry_delay', 'retry'),
                    branch('retry', 'retry_delay'),
                    next('retry', 'exit'),
                ]
            ),
            'exit',
            'Reached 2 days or more after the trigger',
        ],
    ])('%s', (_, workflow, id, expected) => {
        expect(stepText(workflow, id)).toEqual(expected)
    })

    it('gives each arrow out of a wait the time people take it', () => {
        const { edges } = timeFromTrigger(trialFlow)
        expect(reachedAfterTriggerText(edges.get(getEdgeId(next('wait_upgrade', 'last_day'))))).toEqual(
            'Reached 14 days after the trigger'
        )
        expect(reachedAfterTriggerText(edges.get(getEdgeId(branch('wait_upgrade', 'converted'))))).toEqual(
            'Reached 10 days to 14 days after the trigger'
        )
    })

    test.each([
        ['a label the canvas shows in full has no tooltip', 'Event received', undefined, undefined],
        [
            'a shortened label shows its full text and the time',
            'If the person opened the upgrade email within the trial',
            'Reached 2 days after the trigger',
            'If the person opened the upgrade email within the trial. Reached 2 days after the trigger',
        ],
        [
            'a shortened label that ends a sentence is not given a second period',
            'If the person opened the upgrade email within the trial.',
            'Reached 2 days after the trigger',
            'If the person opened the upgrade email within the trial. Reached 2 days after the trigger',
        ],
        [
            'a label the canvas shows in full shows only the time',
            'Event received',
            'Reached 2 days after the trigger',
            'Reached 2 days after the trigger',
        ],
        [
            'an arrow without a label shows the time',
            undefined,
            'Reached 2 days after the trigger',
            'Reached 2 days after the trigger',
        ],
    ])('tooltip: %s', (_, label, reachedAfter, expected) => {
        expect(labelTooltip(label, reachedAfter)).toEqual(expected)
    })

    it('leaves out steps the trigger cannot reach', () => {
        const workflow = flow([step('trigger', 'trigger'), step('orphan')], [])
        expect(timeFromTrigger(workflow).steps.has('orphan')).toBe(false)
    })
})
