import assert from 'node:assert/strict'
import { describe, test } from 'node:test'

import {
    WorkflowError,
    branch,
    delay,
    email,
    fn,
    onEvent,
    onSchedule,
    path,
    person,
    secret,
    webhook,
    workflow,
} from '../src/index.js'
import type {
    Action,
    Duration,
    EmailSenderOptions,
    Path,
    Step,
    WorkflowErrorFields,
    WorkflowVariable,
} from '../src/index.js'

const notifyCrm = webhook({
    name: 'Tell the CRM to follow up',
    url: 'https://example.com/hooks/onboarding',
    body: { distinct_id: '{event.distinct_id}' },
    signingSecret: secret('CRM_TOKEN'),
})

const welcomeEmail = email({
    name: 'Welcome the paid customer',
    from: { integrationIds: [12], name: 'The Example team' },
    to: '{person.properties.email}',
    subject: 'Welcome aboard',
    text: 'Thanks for upgrading.',
    html: '<p>Thanks for upgrading.</p>',
})

const onboarding = workflow({
    key: 'onboarding-nudge',
    name: 'Onboarding nudge',
    on: onEvent({ event: 'user signed up' }),
    steps: path(
        delay('1d', { name: 'Wait a day' }),
        branch({
            name: 'Which plan?',
            branches: [
                {
                    name: 'Paid plan',
                    when: [person('plan', 'exact', ['pro'])],
                    then: path(welcomeEmail, notifyCrm),
                },
                {
                    name: 'Free plan',
                    when: [person('plan', 'exact', ['free'])],
                    then: path(delay('2d', { name: 'Give the free plan two days' }), notifyCrm),
                },
            ],
        })
    ),
    exit: { reason: 'Onboarding nudge finished' },
})

const env = { CRM_TOKEN: 'shhh' }

/** Runs `emit` expecting a refusal, and returns the four fields it carries. */
function refusal(run: () => unknown): WorkflowErrorFields {
    try {
        run()
    } catch (error) {
        assert.ok(error instanceof WorkflowError, `expected a WorkflowError, got ${String(error)}`)
        return error.fields
    }
    throw new Error('expected a WorkflowError, but nothing was thrown')
}

/** A one-step workflow around `steps`, for the cases where only the refusal matters. */
function around(steps: Path, variables?: readonly WorkflowVariable[]): { emit: () => unknown } {
    const flow = workflow({
        key: 'under-test',
        name: 'Under test',
        on: onSchedule(),
        ...(variables === undefined ? {} : { variables }),
        steps,
        exit: { reason: 'Done' },
    })
    return { emit: () => flow.emit({ env }) }
}

function action(actions: readonly Action[], id: string): Action {
    const found = actions.find((candidate) => candidate.id === id)
    assert.ok(found, `no action with id "${id}" in ${actions.map((a) => a.id).join(', ')}`)
    return found
}

function webhookAction(id: string): Action {
    return {
        id,
        name: 'Tell the CRM to follow up',
        type: 'function',
        config: {
            template_id: 'template-webhook',
            inputs: {
                url: { value: 'https://example.com/hooks/onboarding' },
                method: { value: 'POST' },
                body: { value: { distinct_id: '{event.distinct_id}' } },
                signing_secret: { value: 'shhh' },
            },
        },
    }
}

describe('@posthog/workflows', () => {
    // Asserted whole and in order, because the push diffs this JSON against what PostHog
    // stores. A reordered array is a spurious change in every later diff.
    test('emits the workflow definition the API accepts', () => {
        const { definition } = onboarding.emit({ env })

        assert.deepStrictEqual(definition, {
            key: 'onboarding-nudge',
            name: 'Onboarding nudge',
            description: '',
            status: 'draft',
            exit_condition: 'exit_only_at_end',
            variables: [],
            actions: [
                {
                    id: 'trigger_node',
                    name: 'Trigger',
                    type: 'trigger',
                    config: {
                        type: 'event',
                        filters: {
                            events: [
                                {
                                    id: 'user signed up',
                                    name: 'user signed up',
                                    type: 'events',
                                    order: 0,
                                    properties: [],
                                },
                            ],
                            properties: [],
                            filter_test_accounts: false,
                        },
                    },
                },
                { id: 'wait_a_day', name: 'Wait a day', type: 'delay', config: { delay_duration: '1d' } },
                {
                    id: 'which_plan',
                    name: 'Which plan?',
                    type: 'conditional_branch',
                    config: {
                        conditions: [
                            {
                                name: 'Paid plan',
                                filters: { properties: [person('plan', 'exact', ['pro'])] },
                            },
                            {
                                name: 'Free plan',
                                filters: { properties: [person('plan', 'exact', ['free'])] },
                            },
                        ],
                    },
                },
                {
                    id: 'welcome_the_paid_customer',
                    name: 'Welcome the paid customer',
                    type: 'function_email',
                    config: {
                        template_id: 'template-email',
                        inputs: {
                            email: {
                                // The stored shape: `from` as the runtime reads it, and the html
                                // body again inside the design PostHog would otherwise build on
                                // write, so a second push finds nothing changed.
                                value: {
                                    from: { integrationId: 12, integrationIds: [12], name: 'The Example team' },
                                    to: { email: '{person.properties.email}' },
                                    subject: 'Welcome aboard',
                                    text: 'Thanks for upgrading.',
                                    html: '<p>Thanks for upgrading.</p>',
                                    design: {
                                        counters: { u_row: 1, u_column: 1, u_content_html: 1 },
                                        schemaVersion: 16,
                                        body: {
                                            id: 'html-wrap-body',
                                            headers: [],
                                            footers: [],
                                            rows: [
                                                {
                                                    id: 'html-wrap-row',
                                                    cells: [1],
                                                    columns: [
                                                        {
                                                            id: 'html-wrap-column',
                                                            contents: [
                                                                {
                                                                    id: 'html-wrap-content',
                                                                    type: 'html',
                                                                    values: {
                                                                        html: '<p>Thanks for upgrading.</p>',
                                                                        _meta: {
                                                                            htmlID: 'u_content_html_1',
                                                                            htmlClassNames: 'u_content_html',
                                                                        },
                                                                    },
                                                                },
                                                            ],
                                                            values: {
                                                                _meta: {
                                                                    htmlID: 'u_column_1',
                                                                    htmlClassNames: 'u_column',
                                                                },
                                                            },
                                                        },
                                                    ],
                                                    values: { _meta: { htmlID: 'u_row_1', htmlClassNames: 'u_row' } },
                                                },
                                            ],
                                            values: {},
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
                webhookAction('tell_the_crm_to_follow_up'),
                {
                    id: 'give_the_free_plan_two_days',
                    name: 'Give the free plan two days',
                    type: 'delay',
                    config: { delay_duration: '2d' },
                },
                webhookAction('tell_the_crm_to_follow_up_2'),
                { id: 'exit_node', name: 'Exit', type: 'exit', config: { reason: 'Onboarding nudge finished' } },
            ],
            edges: [
                { from: 'trigger_node', to: 'wait_a_day', type: 'continue' },
                { from: 'wait_a_day', to: 'which_plan', type: 'continue' },
                { from: 'which_plan', to: 'exit_node', type: 'continue' },
                { from: 'welcome_the_paid_customer', to: 'tell_the_crm_to_follow_up', type: 'continue' },
                { from: 'tell_the_crm_to_follow_up', to: 'exit_node', type: 'continue' },
                { from: 'which_plan', to: 'welcome_the_paid_customer', type: 'branch', index: 0 },
                { from: 'give_the_free_plan_two_days', to: 'tell_the_crm_to_follow_up_2', type: 'continue' },
                { from: 'tell_the_crm_to_follow_up_2', to: 'exit_node', type: 'continue' },
                { from: 'which_plan', to: 'give_the_free_plan_two_days', type: 'branch', index: 1 },
            ],
        })
    })

    test('emits the same bytes every time, so an unchanged file diffs as no change', () => {
        const first = onboarding.emit({ env }).definition
        const second = onboarding.emit({ env }).definition

        assert.strictEqual(JSON.stringify(second), JSON.stringify(first))
    })

    test('does not let an edit to one definition reach the next emit', () => {
        const first = onboarding.emit({ env }).definition
        const before = JSON.stringify(first)
        const emailAction = action(first.actions, 'welcome_the_paid_customer')
        assert.ok(emailAction.type === 'function_email')
        ;(emailAction.config.inputs.email.value as { subject: string }).subject = 'Tampered'

        assert.strictEqual(JSON.stringify(onboarding.emit({ env }).definition), before)
    })

    test('makes one node per placement, so a reused step is not one shared node', () => {
        const { definition } = onboarding.emit({ env })
        const placements = definition.actions.filter((candidate) => candidate.name === 'Tell the CRM to follow up')

        assert.deepStrictEqual(
            placements.map((candidate) => candidate.id),
            ['tell_the_crm_to_follow_up', 'tell_the_crm_to_follow_up_2']
        )
    })

    // Appending to the trunk must not renumber a placement inside an earlier branch: PostHog
    // moves in-flight participants between steps by string equality of the action id.
    test('keeps every existing action id when a step is appended to the trunk', () => {
        const reused = delay('1d', { name: 'Cool off' })
        const steps = (extra: readonly Step[]): Path =>
            [
                branch({
                    name: 'Which plan?',
                    branches: [{ name: 'Paid plan', when: [person('plan', 'exact', ['pro'])], then: path(reused) }],
                }),
                ...extra,
            ] as unknown as Path

        const before = around(steps([])).emit()
        const after = around(steps([reused])).emit()
        const ids = (result: unknown): string[] =>
            (result as { definition: { actions: readonly Action[] } }).definition.actions.map(
                (candidate) => candidate.id
            )

        assert.deepStrictEqual(ids(before), ['trigger_node', 'which_plan', 'cool_off', 'exit_node'])
        assert.deepStrictEqual(ids(after), ['trigger_node', 'which_plan', 'cool_off', 'cool_off_2', 'exit_node'])
    })

    test('sends the resolved secret at every placement and never the variable name', () => {
        const { definition, secretInputs } = onboarding.emit({ env })

        assert.ok(!JSON.stringify(definition).includes('CRM_TOKEN'))
        assert.deepStrictEqual(secretInputs, [
            { actionId: 'tell_the_crm_to_follow_up', inputKey: 'signing_secret', envName: 'CRM_TOKEN' },
            { actionId: 'tell_the_crm_to_follow_up_2', inputKey: 'signing_secret', envName: 'CRM_TOKEN' },
        ])
    })

    test('reads the secret from process.env when no environment is passed', () => {
        process.env.CRM_TOKEN = 'from-the-process'
        try {
            const value = action(onboarding.emit().definition.actions, 'tell_the_crm_to_follow_up')
            assert.ok(value.type === 'function')
            assert.deepStrictEqual(value.config.inputs.signing_secret, { value: 'from-the-process' })
        } finally {
            delete process.env.CRM_TOKEN
        }
    })

    for (const [label, broken] of [
        ['unset', {}],
        ['set to an empty string', { CRM_TOKEN: '' }],
    ] as const) {
        test(`refuses to emit when the secret variable is ${label}`, () => {
            assert.deepStrictEqual(
                refusal(() => onboarding.emit({ env: broken })),
                {
                    status: 'missing_secret',
                    message: 'The environment variable CRM_TOKEN is not set or is empty.',
                    why: 'Step "Tell the CRM to follow up" names CRM_TOKEN for the secret input "signing_secret". A secret is always sent rather than read back from PostHog, so there is nothing to send.',
                    fix: 'Set CRM_TOKEN in the environment that runs the push, then push again.',
                }
            )
        })
    }

    for (const [label, step] of [
        [
            'nested inside a function input',
            fn({
                name: 'Call the API',
                templateId: 'template-webhook',
                inputs: { headers: { Authorization: secret('CRM_TOKEN') } },
            }),
        ],
        [
            'on an email field',
            email({
                name: 'Welcome',
                from: { integrationIds: [12] },
                to: 'someone@example.com',
                subject: secret('CRM_TOKEN') as unknown as string,
                text: 'Hello',
                html: '<p>Hello</p>',
            }),
        ],
    ] as const) {
        test(`refuses a secret ${label}, which would send the variable name`, () => {
            assert.strictEqual(refusal(around(path(step)).emit).status, 'nested_secret')
        })
    }

    const emailFrom = (from: EmailSenderOptions): Step =>
        email({ name: 'Welcome', from, to: 'someone@example.com', subject: 'Hi', text: 'Hello', html: '<p>Hello</p>' })

    // PostHog refuses these on write, or the runtime fails the send, and neither says why in
    // terms of the file.
    for (const [label, from, status] of [
        [
            'no sender id, which the type refuses but a cast lets through',
            { integrationIds: [] },
            'invalid_email_sender',
        ],
        ['more than ten sender ids', { integrationIds: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11] }, 'invalid_email_sender'],
        ['a sender id that is not an integer', { integrationIds: [1.5] }, 'invalid_email_sender'],
        [
            'a hole in the sender list, which find would mistake for nothing',
            { integrationIds: [1, undefined] },
            'invalid_email_sender',
        ],
        ['a sender id that is not positive', { integrationIds: [0] }, 'invalid_email_sender'],
        ['no sender at all, which a file written for another shape passes', undefined, 'invalid_email_sender'],
        [
            'a sender address that is not an address',
            { integrationIds: [12], email: 'the team' },
            'invalid_sender_address',
        ],
    ] as const) {
        test(`refuses an email with ${label}`, () => {
            const bad = around(path(emailFrom(from as unknown as EmailSenderOptions)))

            assert.strictEqual(refusal(bad.emit).status, status)
        })
    }

    for (const [label, address] of [
        ['a literal address', 'team@example.com'],
        ['hog templating, which resolves at send time', '{person.properties.owner_email}'],
    ] as const) {
        test(`accepts ${label} as the sender address`, () => {
            assert.doesNotThrow(around(path(emailFrom({ integrationIds: [12], email: address }))).emit)
        })
    }

    test('does not mistake a string holding the marker for a secret', () => {
        const step = fn({
            name: 'Call the API',
            templateId: 'template-webhook',
            inputs: { body: { note: 'the __secret sauce' } },
        })

        assert.doesNotThrow(around(path(step)).emit)
    })

    test('refuses two steps whose names produce the same action id', () => {
        const collide = around(path(delay('1d', { name: 'Wait!' }), delay('2d', { name: 'Wait' })))

        assert.deepStrictEqual(refusal(collide.emit), {
            status: 'duplicate_action_id',
            message: 'Two steps produce the action id "wait".',
            why: 'An action id is the slug of the step name. Step 1 ("Wait!") and step 2 ("Wait") in graph order produce the same id. PostHog keys a workflow\'s in-flight participants and its secrets on the action id, so two steps cannot share one.',
            fix: 'Rename one of the steps, or give one an explicit id.',
        })
    })

    test('names both positions when two steps share a name, which a name alone cannot tell apart', () => {
        const collide = around(path(delay('1d', { name: 'Wait' }), delay('2d', { name: 'Wait' })))
        const fields = refusal(collide.emit)

        assert.ok(fields.why.includes('Step 1 ("Wait") and step 2 ("Wait")'), fields.why)
    })

    test('refuses two explicit ids that collide, and says to change the id rather than the name', () => {
        const collide = around(
            path(delay('1d', { name: 'First', id: 'cool_off' }), delay('2d', { name: 'Second', id: 'cool_off' }))
        )

        assert.deepStrictEqual(refusal(collide.emit), {
            status: 'duplicate_action_id',
            message: 'Two steps are given the action id "cool_off".',
            why: 'Step 1 ("First") and step 2 ("Second") in graph order both set it. PostHog keys a workflow\'s in-flight participants and its secrets on the action id, so two steps cannot share one.',
            fix: 'Change the id on one of them.',
        })
    })

    for (const [label, name, taken] of [
        ['the trigger', 'Trigger node', 'trigger_node'],
        ['the exit', 'Exit node', 'exit_node'],
    ] as const) {
        test(`refuses a step name that takes the id of ${label}`, () => {
            const fields = refusal(around(path(delay('1d', { name }))).emit)

            assert.strictEqual(fields.status, 'reserved_action_id')
            assert.ok(fields.message.includes(taken), fields.message)
        })
    }

    test('pins an action id to the explicit id, so a rename keeps the old id', () => {
        const renamed = around(path(delay('1d', { name: 'Wait a whole day', id: 'wait_a_day' })))

        assert.deepStrictEqual(
            action((renamed.emit() as { definition: { actions: Action[] } }).definition.actions, 'wait_a_day'),
            {
                id: 'wait_a_day',
                name: 'Wait a whole day',
                type: 'delay',
                config: { delay_duration: '1d' },
            }
        )
    })

    for (const [label, id] of [
        ['empty', ''],
        ['only whitespace', '  '],
        ['punctuated', 'wait.a.day'],
        ['longer than 200 characters', 'a'.repeat(201)],
    ] as const) {
        test(`refuses an explicit action id that is ${label}`, () => {
            const bad = around(path(delay('1d', { name: 'Wait', id })))

            assert.strictEqual(refusal(bad.emit).status, 'invalid_action_id')
        })
    }

    test('refuses a step name that slugs to nothing rather than inventing an id', () => {
        const fields = refusal(around(path(delay('1d', { name: '日本語のステップ' }))).emit)

        assert.strictEqual(fields.status, 'unnamed_action_id')
        assert.strictEqual(fields.fix, 'Give the step an explicit id.')
    })

    test('refuses a step name longer than the field PostHog stores it in', () => {
        const fields = refusal(around(path(delay('1d', { name: 'W'.repeat(401) }))).emit)

        assert.strictEqual(fields.status, 'step_name_too_long')
    })

    test('refuses a generated action id longer than PostHog accepts', () => {
        const fields = refusal(around(path(delay('1d', { name: 'w '.repeat(120) }))).emit)

        assert.strictEqual(fields.status, 'action_id_too_long')
    })

    for (const [label, duration] of [
        ['a negative duration', '-1d'],
        ['an exponential duration', '1e3d'],
        ['a duration that is not finite', 'Infinityd'],
        ['a duration without a unit', '30'],
        ['a wait of zero', '0m'],
    ] as const) {
        test(`refuses ${label} that the type lets through`, () => {
            const bad = around(path(delay(duration as Duration, { name: 'Wait' })))

            assert.strictEqual(refusal(bad.emit).status, 'invalid_duration')
        })
    }

    // The runtime clamps the amount to the cap for its unit and reports nothing, so `90m`
    // would silently wait an hour.
    for (const [duration, suggestion] of [
        ['90m', 'Use the larger unit: write "1.5h".'],
        ['120s', 'Use the larger unit: write "2m".'],
        ['48h', 'Use the larger unit: write "2d".'],
        ['60d', 'The longest wait PostHog supports is 30d. Split the wait across two steps.'],
    ] as const) {
        test(`refuses "${duration}", which the runtime would clamp`, () => {
            const bad = around(path(delay(duration, { name: 'Wait' })))
            const fields = refusal(bad.emit)

            assert.strictEqual(fields.status, 'duration_over_unit_cap')
            assert.strictEqual(fields.fix, suggestion)
        })
    }

    test('refuses a branch whose path is empty, which would make the branch decide nothing', () => {
        const empty = around(
            path(
                branch({
                    name: 'Which plan?',
                    branches: [
                        {
                            name: 'Paid plan',
                            when: [person('plan', 'exact', ['pro'])],
                            then: [] as unknown as Path,
                        },
                    ],
                })
            )
        )

        assert.strictEqual(refusal(empty.emit).status, 'empty_path')
    })

    for (const [label, variables, status] of [
        [
            'duplicate keys',
            [
                { key: 'plan', type: 'string', default: 'free' },
                { key: 'plan', type: 'string', default: 'pro' },
            ],
            'duplicate_variable_key',
        ],
        [
            'more than 5120 bytes in total',
            [{ key: 'blob', type: 'string', default: 'x'.repeat(5200) }],
            'variables_too_large',
        ],
    ] as const) {
        test(`refuses variables with ${label}`, () => {
            const bad = around(path(delay('1d', { name: 'Wait' })), variables as readonly WorkflowVariable[])

            assert.strictEqual(refusal(bad.emit).status, status)
        })
    }

    test('defaults the status to draft, so a first push sends nothing to a real person', () => {
        const flow = workflow({
            key: 'status',
            name: 'Status',
            on: onSchedule(),
            steps: path(delay('1d', { name: 'Wait' })),
            exit: { reason: 'Done' },
        })

        assert.strictEqual(flow.emit({ env }).definition.status, 'draft')
    })

    test('carries the status and the variables the file declares', () => {
        const flow = workflow({
            key: 'with-variables',
            name: 'With variables',
            status: 'active',
            on: onSchedule(),
            variables: [{ key: 'plan', type: 'string', default: 'free' }],
            steps: path(delay('1d', { name: 'Wait' })),
            exit: { reason: 'Done' },
        })

        const { definition } = flow.emit({ env })
        assert.strictEqual(definition.status, 'active')
        assert.deepStrictEqual(definition.variables, [{ key: 'plan', type: 'string', default: 'free' }])
    })

    test('wraps every escape-hatch input value, so hog templating resolves', () => {
        const flow = around(
            path(
                fn({
                    name: 'Post to Slack',
                    templateId: 'template-slack',
                    inputs: { text: 'Hello {person.properties.email}', blocks: [] },
                })
            )
        )

        const actions = (flow.emit() as { definition: { actions: Action[] } }).definition.actions
        assert.deepStrictEqual(action(actions, 'post_to_slack'), {
            id: 'post_to_slack',
            name: 'Post to Slack',
            type: 'function',
            config: {
                template_id: 'template-slack',
                inputs: { text: { value: 'Hello {person.properties.email}' }, blocks: { value: [] } },
            },
        })
    })
})
