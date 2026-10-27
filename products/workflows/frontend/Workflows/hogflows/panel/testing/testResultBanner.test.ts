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
})
