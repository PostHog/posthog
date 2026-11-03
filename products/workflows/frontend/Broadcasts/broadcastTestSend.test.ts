import { HogflowTestResult } from '../Workflows/hogflows/steps/types'
import { findPushTestPartialFailure, findPushTestSkipReason } from './broadcastTestSendLogic'

const result = (partial: Partial<HogflowTestResult>): HogflowTestResult =>
    ({ status: 'success', nextActionId: null, ...partial }) as HogflowTestResult

const log = (message: string, level = 'info'): any => ({ level, timestamp: '2026-01-01T00:00:00Z', message })

describe('push test send outcomes', () => {
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
