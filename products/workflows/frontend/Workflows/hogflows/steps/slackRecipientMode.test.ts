import { switchSlackRecipientMode } from './slackRecipientMode'

describe('switchSlackRecipientMode', () => {
    it.each([
        {
            name: 'a channel step keeps its workspace and message when it switches to a team member',
            inputs: {
                slack_workspace: { value: 7 },
                channel: { value: 'C123' },
                blocks: { value: [] },
                text: { value: 'Ticket needs you' },
            },
            mode: 'team_member' as const,
            expected: {
                template_id: 'template-posthog-slack-dm-team-member',
                inputs: { slack_workspace: { value: 7 }, text: { value: 'Ticket needs you' } },
            },
        },
        {
            name: 'a team member step drops its recipient when it switches back to a channel',
            inputs: { slack_workspace: { value: 7 }, recipient: { value: 'ada@example.com' } },
            mode: 'channel' as const,
            expected: { template_id: 'template-slack', inputs: { slack_workspace: { value: 7 } } },
        },
    ])('$name', ({ inputs, mode, expected }) => {
        expect(switchSlackRecipientMode(inputs, mode)).toEqual(expected)
    })
})
