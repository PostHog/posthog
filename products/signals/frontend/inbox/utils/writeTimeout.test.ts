import posthog from 'posthog-js'

import { PromiseTimeoutError } from 'lib/utils/async'

import { INBOX_CLIENT, INBOX_EVENTS } from '../inboxAnalytics'
import { INBOX_WRITE_TIMEOUT_MS, withInboxWriteTimeout } from './writeTimeout'

jest.mock('posthog-js')

describe('withInboxWriteTimeout', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('fails a write that never settles, aborts it, and records which write stalled', async () => {
        let signal: AbortSignal | undefined
        const outcome = withInboxWriteTimeout('claim', (options) => {
            signal = options.signal
            return new Promise<void>(() => {})
        }).catch((error) => error)

        jest.advanceTimersByTime(INBOX_WRITE_TIMEOUT_MS)

        expect(await outcome).toBeInstanceOf(PromiseTimeoutError)
        expect(signal?.aborted).toBe(true)
        expect(
            (posthog.capture as jest.Mock).mock.calls
                .filter(([event]) => event === INBOX_EVENTS.WRITE_TIMED_OUT)
                .map(([, properties]) => properties)
        ).toEqual([{ inbox_client: INBOX_CLIENT, write: 'claim', timeout_ms: INBOX_WRITE_TIMEOUT_MS }])
    })
})
