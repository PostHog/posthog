import { delay, fn, onSchedule, path, workflow } from '@posthog/workflows'

export const weeklyDigest = workflow({
    key: 'weekly-digest',
    name: 'Weekly digest',
    description: 'Posts the weekly numbers to Slack.',
    status: 'active',
    exitCondition: 'exit_on_trigger_not_matched',
    variables: [
        { key: 'team_name', type: 'string', default: 'Example' },
        { key: 'retries', type: 'number', default: '3' },
    ],
    on: onSchedule(),
    steps: path(
        fn({
            name: 'Post the digest',
            id: 'post_digest',
            templateId: 'template-slack',
            inputs: { channel: '#digest', text: 'Weekly digest for {variables.team_name}' },
        }),
        delay('1d', { name: 'Wait a day' }),
    ),
    exit: { reason: 'Posted' },
})
