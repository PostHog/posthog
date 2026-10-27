import type { HogFlow, HogFlowAction } from '../../types'
import { pathSummary, stepBadge, stepFacts, stepView } from './stepFacts'
import { timeWindowSpans } from './stepPresentation'
import { computePathGroups } from './tileCanvasModel'

type Config = Record<string, unknown>

const step = (id: string, type: string, config: Config, name = id): HogFlowAction =>
    ({ id, type, name, description: '', config }) as HogFlowAction

const inputs = (values: Config): Record<string, { value: unknown }> =>
    Object.fromEntries(Object.entries(values).map(([key, value]) => [key, { value }]))

const fn = (id: string, templateId: string, values: Config, extra: Partial<HogFlowAction> = {}): HogFlowAction =>
    ({ ...step(id, 'function', { template_id: templateId, inputs: inputs(values) }), ...extra }) as HogFlowAction

const email = step('welcome', 'function_email', {
    template_id: 'template-email',
    inputs: inputs({
        email: {
            to: { email: '{{ person.properties.email }}' },
            subject: 'Welcome to Example Co.',
            preheader: 'Your first doc takes two minutes',
            html: '<p>Hi</p>',
        },
    }),
})

const workflow = (actions: HogFlowAction[], extra: Partial<HogFlow> = {}): HogFlow =>
    ({
        id: 'flow',
        team_id: 1,
        version: 1,
        name: 'Flow',
        status: 'draft',
        exit_condition: 'exit_only_at_end',
        actions,
        edges: [],
        created_at: '',
        updated_at: '',
        ...extra,
    }) as HogFlow

const eventTrigger = step('trigger', 'trigger', {
    type: 'event',
    filters: { events: [{ id: 'Signed up', name: 'Signed up', type: 'events' }] },
})

const split = step('by_plan', 'conditional_branch', {
    conditions: [
        {
            name: 'Paid',
            filters: { properties: [{ key: 'plan', type: 'person', value: ['paid'], operator: 'exact' }] },
        },
        {
            name: 'Trial',
            filters: { properties: [{ key: 'plan', type: 'person', value: ['trial'], operator: 'exact' }] },
        },
    ],
})

const aiTask = fn(
    'draft_reply',
    'template-posthog-create-task',
    {
        title: 'Answer the question',
        prompt: 'Answer with links to the docs. Say how sure you are.',
        connectors: ['docs-mcp'],
        skills: ['tone-of-voice', 'support-macros'],
    },
    { output_variable: [{ key: 'reply', result_path: 'reply' }] }
)

describe('stepFacts', () => {
    it.each<[string, HogFlowAction, string, string | undefined]>([
        ['an email', email, 'Welcome to Example Co.', 'Your first doc takes two minutes'],
        [
            'an email that greets the person by name',
            step('greet', 'function_email', {
                template_id: 'template-email',
                inputs: inputs({
                    email: {
                        subject: 'Three tricks for {{ person.properties.first_name }}',
                        preheader: 'Picked for {{person.properties.first_name}} and the team',
                    },
                }),
            }),
            'Three tricks for first name',
            'Picked for first name and the team',
        ],
        [
            'a Slack message',
            fn('notify', 'template-slack', {
                channel: 'C123|#support',
                text: 'New ticket: {event.properties.subject}\nOpen it',
            }),
            'Post to #support',
            'New ticket: subject',
        ],
        [
            'a webhook',
            fn('call', 'template-webhook', {
                url: 'https://hooks.example.com/v1/page',
                method: 'POST',
                body: { severity: 'high' },
            }),
            'Call hooks.example.com',
            'Sends severity',
        ],
        ['an AI task', aiTask, 'Answer the question', 'Answer with links to the docs.'],
        [
            'a scout',
            fn('investigate', 'template-posthog-run-scout', { skill_name: 'incident-investigator' }),
            'Run the incident investigator scout',
            undefined,
        ],
        [
            'a ticket reply',
            fn('reply', 'template-posthog-send-ticket-message', { message: 'Thanks, we are on it', is_private: false }),
            'Reply to the customer',
            'Thanks, we are on it',
        ],
        [
            'a ticket note that sends an earlier answer',
            fn('note', 'template-posthog-send-ticket-message', { message: '{variables.ai_reply}', is_private: true }),
            'Save a note for an agent',
            'Sends the ai reply from earlier',
        ],
        [
            'a ticket update',
            fn('route', 'template-posthog-update-ticket', { status: 'pending', tags: ['bug', 'p1'] }),
            'Set status to pending',
            'Tag bug, p1',
        ],
        [
            'a person update',
            fn('mark', 'template-posthog-update-person-properties', { set_properties: { billing_status: 'past_due' } }),
            'Set billing status to past_due',
            'On the person',
        ],
        ['a delay', step('pause', 'delay', { delay_duration: '3d' }), 'Wait 3 days', 'Then continue'],
        [
            'a delay until a date on the person',
            step('remind', 'delay', {
                delay_until: {
                    expression: 'person.properties.trial_expires_at',
                    offset: '-1d',
                    use_person_timezone: true,
                },
            }),
            'Wait until 1 day before trial expires at',
            "Then continue (the person's time zone)",
        ],
        [
            'a delay until a date not chosen yet',
            step('remind', 'delay', { delay_until: { expression: '' } }),
            'Wait until a date',
            'Then continue (UTC)',
        ],
        [
            'a wait for an event',
            step('wait', 'wait_until_condition', { condition: { name: 'Upgraded' }, max_wait_duration: '4d' }),
            'Wait for Upgraded',
            'Gives up after 4 days',
        ],
        [
            'a wait for an event it has not named yet',
            step('wait', 'wait_until_condition', { condition: { name: '' }, max_wait_duration: '4d' }),
            'Wait for a condition',
            'Gives up after 4 days',
        ],
        [
            'a time window',
            step('hours', 'wait_until_time_window', {
                timezone: 'Europe/Berlin',
                day: 'weekday',
                time: ['09:00', '17:00'],
            }),
            'Next weekday, 09:00 to 17:00',
            'Holds people until then (Europe/Berlin)',
        ],
        ['a split', split, 'Split by plan', 'Paid, Trial, or no match'],
        [
            'a random split',
            step('ab', 'random_cohort_branch', { cohorts: [{ percentage: 50 }, { percentage: 50 }] }),
            'Random split',
            '50% / 50%',
        ],
        [
            'a random split whose weights do not add up to 100',
            step('ab', 'random_cohort_branch', {
                cohorts: [{ percentage: 10 }, { percentage: 10 }, { percentage: 20 }],
            }),
            'Random split',
            '25% / 25% / 50%',
        ],
        ['an event trigger', eventTrigger, 'Signed up', 'Starts when someone does this'],
        [
            'a trigger on a PostHog action',
            step('trigger', 'trigger', {
                type: 'event',
                filters: {
                    events: [{ id: 'Signed up', name: 'Signed up', type: 'events' }],
                    actions: [{ id: 12, name: 'Checked out', type: 'actions' }],
                },
            }),
            'Signed up or Checked out',
            'Starts when someone does this',
        ],
        [
            'an exit',
            step('exit', 'exit', { reason: 'Trial ended' }),
            'Trial ended',
            'Nobody leaves early: everyone runs to the end',
        ],
    ])('leads %s with its own data', (_, action, headline, detail) => {
        expect(stepFacts(workflow([action]), action)).toMatchObject({ headline, detail })
    })

    it.each([
        ['a split', step('draft_split', 'conditional_branch', {}), 'Split by condition', 'No conditions yet'],
        ['a random split', step('draft_random', 'random_cohort_branch', {}), 'Random split', undefined],
        [
            'an event trigger',
            step('trigger', 'trigger', { type: 'event' }),
            'Any event',
            'Starts when someone does this',
        ],
    ])('reads a draft %s that has no paths set up yet', (_, action, headline, detail) => {
        expect(stepFacts(workflow([action]), action)).toMatchObject({ headline, detail })
    })

    it.each([
        ['only events', [{ filters: { events: [{ id: 'Upgraded', name: 'Upgraded' }] } }], {}, 'did Upgraded'],
        [
            'events or a property condition',
            [{ filters: { events: [{ id: 'Upgraded', name: 'Upgraded' }] } }],
            { properties: [{ key: 'plan', type: 'person', value: ['paid'], operator: 'exact' }] },
            'did Upgraded or plan is paid',
        ],
        ['nothing yet', undefined, {}, 'everyone'],
    ])('says what a wait waits for when it has %s', (_, events, filters, waitsFor) => {
        const action = step('wait', 'wait_until_condition', { condition: { filters }, events, max_wait_duration: '4d' })

        expect(stepFacts(workflow([action]), action).fields).toContainEqual(['Waits for', waitsFor])
    })

    it.each([
        ['a yes or no', 'beta', true, 'Set beta to true'],
        ['a number', 'seats', 3, 'Set seats to 3'],
        ['a text', 'billing_status', 'past_due', 'Set billing status to past_due'],
    ])('writes %s person property value as someone would type it', (_, key, value, headline) => {
        const action = fn('mark', 'template-posthog-update-person-properties', { set_properties: { [key]: value } })

        expect(stepFacts(workflow([action]), action).headline).toBe(headline)
    })

    it('reads a step once for all its tiles, and again when its paths change', () => {
        const twoPaths = workflow([split], {
            edges: [
                { from: 'by_plan', to: 'a', type: 'branch', index: 0 },
                { from: 'by_plan', to: 'b', type: 'continue' },
            ],
        })
        const threePaths = workflow([split], {
            edges: [...twoPaths.edges, { from: 'by_plan', to: 'c', type: 'branch', index: 1 }],
        })

        expect(stepView(twoPaths, split)).toBe(stepView(workflow([split], { edges: twoPaths.edges }), split))
        expect(stepView(threePaths, split).badge).toBe('3 paths')
    })

    it.each<[string, Partial<HogFlowAction>, string, string | undefined]>([
        ['shows the template name for a step that keeps it', {}, 'HubSpot', undefined],
        [
            'keeps the name and description the author gave the step',
            { name: 'Stamp the last email date', description: 'So the next run waits a week' },
            'Stamp the last email date',
            'So the next run waits a week',
        ],
        ['names the template under a renamed step', { name: 'Sync the contact' }, 'Sync the contact', 'HubSpot'],
    ])('%s', (_, extra, headline, detail) => {
        const action = fn('hubspot', 'template-hubspot', { email: 'x' }, extra)

        expect(stepFacts(workflow([action]), action, 'HubSpot')).toMatchObject({
            headline,
            detail,
            fields: [['Runs', 'HubSpot']],
        })
    })

    it.each<[string, HogFlowAction, string | undefined]>([
        ['a delay shows its length', step('pause', 'delay', { delay_duration: '3d' }), '3d'],
        [
            'a delay until a date shows that it waits for a date',
            step('remind', 'delay', { delay_until: { expression: 'person.properties.renews_at' } }),
            'Date',
        ],
        [
            'a wait shows its longest wait',
            step('wait', 'wait_until_condition', { condition: {}, max_wait_duration: '4d' }),
            '≤ 4d',
        ],
        [
            'a time window shows its hours',
            step('hours', 'wait_until_time_window', { timezone: null, day: 'any', time: ['09:00', '17:00'] }),
            '09-17',
        ],
        [
            'a time window keeps minutes that are not on the hour',
            step('hours', 'wait_until_time_window', { timezone: null, day: 'any', time: ['09:30', '17:45'] }),
            '09:30-17:45',
        ],
        ['a split shows its paths', split, '2 paths'],
        ['an AI task shows its tools', aiTask, '3 tools'],
        ['a trigger shows its source', eventTrigger, 'Event'],
        ['an email shows nothing', email, undefined],
    ])('badges the key setting: %s', (_, action, badge) => {
        const edges =
            action.type === 'conditional_branch'
                ? [
                      { from: action.id, to: 'a', type: 'branch' as const, index: 0 },
                      { from: action.id, to: 'b', type: 'continue' as const },
                  ]
                : []

        expect(stepBadge(workflow([action], { edges }), action)).toBe(badge)
    })

    it('sums up a collapsed path with its first three steps', () => {
        const flow = workflow(
            [
                split,
                email,
                step('pause', 'delay', { delay_duration: '1d' }),
                fn('notify', 'template-slack', { channel: '#sales', text: 'Hi' }),
                step('exit', 'exit', {}),
                step('other', 'delay', { delay_duration: '2h' }),
            ],
            {
                edges: [
                    { from: 'by_plan', to: 'welcome', type: 'branch', index: 0 },
                    { from: 'welcome', to: 'pause', type: 'continue' },
                    { from: 'pause', to: 'notify', type: 'continue' },
                    { from: 'notify', to: 'exit', type: 'continue' },
                    { from: 'by_plan', to: 'other', type: 'continue' },
                    { from: 'other', to: 'exit', type: 'continue' },
                ],
            }
        )
        const [group] = computePathGroups(flow)

        expect(pathSummary(flow, group)).toBe('Welcome to Example Co., then Wait 1 day, then Post to #sales')
    })

    it('sums up a path in flow order, and stops at a split inside it', () => {
        const innerSplit = step('inner', 'random_cohort_branch', { cohorts: [{ percentage: 50 }, { percentage: 50 }] })
        const flow = workflow(
            [
                step('x', 'delay', { delay_duration: '2h' }),
                innerSplit,
                fn('notify', 'template-slack', { channel: '#sales', text: 'Hi' }),
                step('y', 'delay', { delay_duration: '3h' }),
                step('exit', 'exit', {}),
                step('other', 'delay', { delay_duration: '2h' }),
                split,
            ],
            {
                edges: [
                    { from: 'by_plan', to: 'notify', type: 'branch', index: 0 },
                    { from: 'notify', to: 'inner', type: 'continue' },
                    { from: 'inner', to: 'x', type: 'branch', index: 0 },
                    { from: 'inner', to: 'y', type: 'continue' },
                    { from: 'x', to: 'exit', type: 'continue' },
                    { from: 'y', to: 'exit', type: 'continue' },
                    { from: 'by_plan', to: 'other', type: 'continue' },
                    { from: 'other', to: 'exit', type: 'continue' },
                ],
            }
        )
        const group = computePathGroups(flow).find((candidate) => candidate.branchActionId === 'by_plan')!

        expect(pathSummary(flow, group)).toBe('Post to #sales, then Random split')
    })

    it.each([
        {
            name: 'keeps the minutes of a short window',
            config: { day: 'weekday', time: ['09:30', '09:45'] },
            expected: [...Array(5).fill([{ start: 9.5, end: 9.75 }]), [], []],
        },
        {
            name: 'splits an overnight window, carrying the morning part to the next day',
            config: { day: ['friday'], time: ['23:00', '01:00'] },
            expected: [[], [], [], [], [{ start: 23, end: 24 }], [{ start: 0, end: 1 }], []],
        },
        {
            name: 'fills a whole open day',
            config: { day: 'weekend', time: 'any' },
            expected: [[], [], [], [], [], [{ start: 0, end: 24 }], [{ start: 0, end: 24 }]],
        },
    ])('maps a time window onto the week: $name', ({ config, expected }) => {
        const action = step('window', 'wait_until_time_window', config) as Extract<
            HogFlowAction,
            { type: 'wait_until_time_window' }
        >

        expect(timeWindowSpans(action.config)).toEqual(expected)
    })
})
