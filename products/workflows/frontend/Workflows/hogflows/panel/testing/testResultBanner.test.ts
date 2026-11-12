import { HogflowTestResult } from '../../steps/types'
import { testResultBanner } from './testResultBanner'

const result = (partial: Partial<HogflowTestResult>): HogflowTestResult =>
    ({ status: 'success', nextActionId: null, ...partial }) as HogflowTestResult

describe('testResultBanner', () => {
    it.each([
        [
            'a delivered email',
            result({ emailSendResult: { status: 'accepted' } }),
            { type: 'success', children: 'Success' },
        ],
        [
            'a declined email',
            result({
                emailSendResult: {
                    status: 'skipped',
                    reason: 'Skipping send: the domain "example.com" has no reachable mail servers, so this message would hard bounce.',
                },
            }),
            {
                type: 'warning',
                children:
                    'Skipping send: the domain "example.com" has no reachable mail servers, so this message would hard bounce.',
            },
        ],
        [
            'a run the filters skipped',
            result({ status: 'skipped' }),
            { type: 'warning', children: 'Workflow was skipped because the event did not match the filter criteria' },
        ],
        [
            'a failed run',
            result({ status: 'error', errors: ['Template not found', 'Missing input'] }),
            { type: 'error', children: 'Error: Template not found, Missing input' },
        ],
    ])('describes %s', (_name, input, expected) => {
        expect(testResultBanner(input)).toEqual(expected)
    })

    it.each([
        ['a sent email', { status: 'accepted' }, 'success', 'Sent from the sandbox sender.'],
        [
            'a mocked run',
            { status: 'accepted', mocked: true },
            'success',
            'Test passed without sending. Turn on real HTTP requests to send from the sandbox sender.',
        ],
        [
            'a recipient who is not a member',
            { status: 'skipped', reason: 'not_member' },
            'warning',
            'Not sent. The sandbox sender only delivers to verified members of your organization.',
        ],
        [
            'a send that can be retried',
            { status: 'pending', reason: 'pause_state_unavailable' },
            'warning',
            "Not sent yet. Couldn't check whether the sandbox sender is available. Try again in a few minutes.",
        ],
        [
            'a project whose email sending is suspended',
            { status: 'skipped', reason: 'sending_suspended' },
            'warning',
            'Not sent. Email sending is suspended for this project. Contact support to get sending re-enabled.',
        ],
        [
            'a workflow whose email sending is paused',
            { status: 'skipped', reason: 'sending_paused' },
            'warning',
            'Not sent. Email sending is paused for this workflow. Resume sending, then send the test again.',
        ],
        [
            'a send whose suspension state could not be read',
            { status: 'pending', reason: 'suspension_state_unavailable' },
            'warning',
            "Not sent yet. Couldn't check whether this project can send email. Try again in a few minutes.",
        ],
        [
            'a send over the rate limit',
            { status: 'failed', reason: 'send_rate_limited' },
            'error',
            "Couldn't send. Too many emails are being sent right now. Send the test again in a moment.",
        ],
        [
            'a send that could not reach the sandbox sender',
            { status: 'pending', reason: 'sandbox_worker_unreachable' },
            'warning',
            "Not sent yet. The sandbox sender couldn't be reached. Try again in a few minutes.",
        ],
        [
            'a step whose id the sandbox sender cannot tag',
            { status: 'failed', reason: 'unsupported_action_id' },
            'error',
            "Couldn't send. The sandbox sender can't send from this step. Delete the step and add it again.",
        ],
        [
            'a failed send with an unknown reason',
            { status: 'failed', reason: 'something_new' },
            'error',
            "Couldn't send. Reason: something_new.",
        ],
    ])('describes %s from the sandbox sender', (_name, execResult, type, children) => {
        const { mocked, ...sent } = execResult as typeof execResult & { mocked?: boolean }
        const failed = sent.status === 'failed'
        const testResult = result({
            execResult: sent,
            mocked,
            ...(failed ? { status: 'error', errors: ['not sent'] } : {}),
        })

        expect(testResultBanner(testResult, 'email_sandbox')).toEqual({ type, children })
    })

    it('reads a sandbox-shaped answer from another step as an ordinary result', () => {
        expect(testResultBanner(result({ execResult: { status: 'accepted' } }), 'function')).toEqual({
            type: 'success',
            children: 'Success',
        })
    })
})
