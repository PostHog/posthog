import { HogflowTestResult } from '../Workflows/hogflows/steps/types'
import { findPushTestPartialFailure, findPushTestSkipReason, findTestSendSkipReason } from './broadcastTestSendLogic'

const result = (partial: Partial<HogflowTestResult>): HogflowTestResult =>
    ({ status: 'success', nextActionId: null, ...partial }) as HogflowTestResult

const log = (message: string, level = 'info'): any => ({ level, timestamp: '2026-01-01T00:00:00Z', message })

describe('test send skip reasons', () => {
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

    it.each([
        [
            'a person with no registered device',
            result({ logs: [log('No active FCM device token found for distinct_id: me', 'warn')] }),
            'No active FCM device token found for distinct_id: me',
        ],
        [
            'an app that took the notification',
            result({ logs: [log('Push notification accepted by FCM for 1 of 1 device(s).')] }),
            undefined,
        ],
        ['a failed run, which reports its own error', result({ status: 'error' }), undefined],
    ])('reports whether a push test reached a device for %s', (_name, input, expected) => {
        expect(findPushTestSkipReason(input)).toBe(expected)
    })

    it.each([
        [
            'one app accepted and another failed',
            result({
                logs: [
                    log('[Action:a] Push notification accepted by FCM for 1 of 1 device(s).'),
                    log('[Action:a] APNs: BadDeviceToken', 'warn'),
                ],
            }),
            '[Action:a] APNs: BadDeviceToken',
        ],
        [
            'one app accepted and the other had no device',
            result({
                logs: [
                    log('[Action:a] Push notification accepted by FCM for 1 of 1 device(s).'),
                    log('[Action:a] No active APNS device token found for distinct_id: me', 'warn'),
                ],
            }),
            undefined,
        ],
    ])('reports app errors behind a delivered push test when %s', (_name, input, expected) => {
        expect(findPushTestPartialFailure(input)).toBe(expected)
    })
})
