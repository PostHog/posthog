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
