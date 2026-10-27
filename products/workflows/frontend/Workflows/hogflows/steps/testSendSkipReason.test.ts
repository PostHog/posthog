import { findTestSendSkipReason } from './testSendSkipReason'
import { HogflowTestResult } from './types'

const result = (partial: Partial<HogflowTestResult>): HogflowTestResult =>
    ({ status: 'success', nextActionId: null, ...partial }) as HogflowTestResult

describe('findTestSendSkipReason', () => {
    it.each([
        'Skipping send: the domain "example.com" has no reachable mail servers, so this message would hard bounce.',
        'Recipient has opted out, skipping message delivery.',
    ])('finds the reason a declined send reports, even though the run says success: %s', (reason) => {
        expect(
            findTestSendSkipReason(result({ status: 'success', emailSendResult: { status: 'skipped', reason } }))
        ).toBe(reason)
    })

    it.each([
        ['a delivered send', result({ status: 'success', emailSendResult: { status: 'accepted' } })],
        ['a run without an email send', result({ status: 'success' })],
        ['no result at all', null],
    ])('reports no reason for %s', (_name, input) => {
        expect(findTestSendSkipReason(input)).toBeUndefined()
    })
})
