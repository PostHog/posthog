import { HogflowTestResult } from '../Workflows/hogflows/steps/types'
import { findTestSendSkipReason } from './broadcastTestSendLogic'

const result = (partial: Partial<HogflowTestResult>): HogflowTestResult =>
    ({ status: 'success', nextActionId: null, ...partial }) as HogflowTestResult

const log = (message: string): any => ({ level: 'info', timestamp: '2026-01-01T00:00:00Z', message })

describe('findTestSendSkipReason', () => {
    it('finds the reason a declined send reports, even though the run says success', () => {
        // The worker declines the send but finishes the step, so status alone would read as sent.
        const reason =
            'Skipping send: the domain "example.com" has no reachable mail servers, so this message would hard bounce.'
        expect(
            findTestSendSkipReason(
                result({ status: 'success', logs: [log('Executing action [Action:send_test_email]'), log(reason)] })
            )
        ).toBe(reason)
    })

    it.each([
        ['a delivered send', result({ status: 'success', logs: [log('Executing action [Action:send_test_email]')] })],
        ['a run with no logs', result({ status: 'success' })],
        ['no result at all', null],
    ])('reports no reason for %s', (_name, input) => {
        expect(findTestSendSkipReason(input)).toBeUndefined()
    })
})
