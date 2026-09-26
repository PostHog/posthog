// `tsc` fails this file when an `@ts-expect-error` line stops being an error, so a
// type rule that relaxes breaks the build.

import {
    branch,
    delay,
    email,
    fn,
    group,
    onSchedule,
    path,
    person,
    secret,
    step,
    trigger,
    workflow,
} from '../src/index.js'

const wait = delay('1d', { name: 'Wait a day' })
const onPaidPlan = [person('plan', 'exact', ['pro'])] as const

// A duration is a number plus a unit, including where the value reaches the call through a const.
const soon = 'soon'
// @ts-expect-error - 'soon' is not a duration
delay(soon, { name: 'Wait' })

// A sub-path is a non-empty tuple, so an empty branch cannot compile.
branch({
    name: 'Which plan?',
    branches: [
        {
            name: 'Paid plan',
            when: onPaidPlan,
            // @ts-expect-error - an empty branch path emits a branch edge aimed at the no-match target
            then: [],
        },
    ],
})

// A branch needs at least one branch.
branch({
    name: 'Which plan?',
    // @ts-expect-error - a branch with no branches is a conditional that decides nothing
    branches: [],
})

// A path needs at least one step.
// @ts-expect-error - an empty workflow has no first action for the trigger to point at
path()

// Email content is inline. A library template is materialized on write, so the stored
// definition would never match the one we sent.
email({
    name: 'Welcome',
    from: { integrationIds: [12] },
    to: 'someone@example.com',
    subject: 'Welcome',
    text: 'Hello',
    html: '<p>Hello</p>',
    // @ts-expect-error - the SDK has no `templateUuid`
    templateUuid: '0199d0c0-0000-7000-8000-000000000000',
})

// An email names its sender. PostHog refuses to save a step without one, and the runtime
// sends from nothing else.
// @ts-expect-error - `from` is required
email({
    name: 'Welcome',
    to: 'someone@example.com',
    subject: 'Welcome',
    text: 'Hello',
    html: '<p>Hello</p>',
})
email({
    name: 'Welcome',
    // @ts-expect-error - the sender list is a non-empty tuple
    from: { integrationIds: [] },
    to: 'someone@example.com',
    subject: 'Welcome',
    text: 'Hello',
    html: '<p>Hello</p>',
})

fn({
    name: 'Post to Slack',
    templateId: 'template-slack',
    inputs: { text: 'Hello', secret: secret('SLACK_TOKEN'), blocks: [{ type: 'section' }] },
})
fn({
    name: 'Post to Slack',
    templateId: 'template-slack',
    inputs: {
        // @ts-expect-error - function inputs must be JSON or a secret
        transform: () => 'Hello',
    },
})

// The workflow carries its own identity.
// @ts-expect-error - `key` is how push finds the workflow again, so it is required
workflow({
    name: 'No key',
    on: onSchedule(),
    steps: path(wait),
    exit: { reason: 'Done' },
})

// A conversion exit needs a conversion goal, and the compiler emits none, so the exit
// would never fire.
workflow({
    key: 'converts',
    name: 'Converts',
    // @ts-expect-error - the conversion variants arrive together with the goal
    exitCondition: 'exit_on_conversion',
    on: onSchedule(),
    steps: path(wait),
    exit: { reason: 'Done' },
})

// Group conditions need the group type index PostHog uses to resolve the property.
// @ts-expect-error - groupTypeIndex is required
const accountTier = group('tier', 'exact', ['enterprise'])
void accountTier

step({
    type: 'function_sms',
    name: 'Send a text message',
    config: { template_id: 'template-twilio', inputs: { message: { value: 'Hello' } } },
    on_error: 'continue',
    output_variable: { key: 'sms_result', label: 'SMS result' },
})
step({
    type: 'function_sms',
    name: 'Send a secret text',
    config: { template_id: 'template-twilio', inputs: { message: secret('SMS_MESSAGE') } },
})
step({
    type: 'function_sms',
    name: 'Send a text with a misplaced secret',
    // @ts-expect-error - a secret is accepted only as a whole entry of config.inputs
    config: { template_id: 'template-twilio', auth: { token: secret('SMS_TOKEN') } },
})

trigger({ type: 'webhook', inputs: { auth_header: secret('WEBHOOK_AUTH') } })
// @ts-expect-error - a secret is accepted only as a whole entry of config.inputs
trigger({ type: 'webhook', auth: { header: secret('WEBHOOK_AUTH') } })

workflow({
    key: 'manual-start',
    name: 'Manual start',
    on: trigger(
        {
            type: 'manual',
            template_id: 'template-source-webhook',
            inputs: { event: { value: '$workflow_triggered' }, distinct_id: { value: '{request.body.user_id}' } },
        },
        { name: 'Manual trigger' }
    ),
    steps: path(wait),
    variables: [{ key: 'plan', type: 'string', default: 'free', label: 'Plan' }],
    exit: { name: 'Finished', description: 'Done without errors.', reason: 'Done' },
})

person('email', 'icontains', 'example.com')
person('email', 'is_set')
person('version', 'semver_gte', '1.2.3')
// @ts-expect-error - value operators need a value
person('email', 'icontains')
// @ts-expect-error - set operators need no author value
person('email', 'is_set', 'yes')
