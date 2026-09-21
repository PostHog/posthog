// `tsc` fails this file when an `@ts-expect-error` line stops being an error, so a
// type rule that relaxes breaks the build.

import { branch, delay, email, onSchedule, path, person, workflow } from '../src/index.js'

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
    to: 'someone@example.com',
    subject: 'Welcome',
    text: 'Hello',
    html: '<p>Hello</p>',
    // @ts-expect-error - the SDK has no `templateUuid`
    templateUuid: '0199d0c0-0000-7000-8000-000000000000',
})

// The workflow carries its own identity.
// @ts-expect-error - `key` is how push finds the workflow again, so it is required
workflow({
    name: 'No key',
    on: onSchedule(),
    steps: path(wait),
    exit: { reason: 'Done' },
})
