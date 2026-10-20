import posthog from 'posthog-js'

import { PromiseTimeoutError } from 'lib/utils/async'

import { INBOX_CLIENT, INBOX_EVENTS } from '../inboxAnalytics'
import { PANEL_LOAD_TIMEOUT_MS, withPanelLoadTimeout } from './panelLoadTimeout'

jest.mock('posthog-js')

function timeoutCaptures(): Record<string, any>[] {
    return (posthog.capture as jest.Mock).mock.calls
        .filter(([event]) => event === INBOX_EVENTS.PANEL_LOAD_TIMED_OUT)
        .map(([, properties]) => properties)
}

describe('withPanelLoadTimeout', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        ;(posthog.capture as jest.Mock).mockClear()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('records which read stalled when the bound expires', async () => {
        const outcome = withPanelLoadTimeout('scout_notes', () => new Promise<string[]>(() => {})).catch(
            (error) => error
        )

        jest.advanceTimersByTime(PANEL_LOAD_TIMEOUT_MS)

        expect(await outcome).toBeInstanceOf(PromiseTimeoutError)
        expect(timeoutCaptures()).toEqual([
            { inbox_client: INBOX_CLIENT, load: 'scout_notes', timeout_ms: PANEL_LOAD_TIMEOUT_MS },
        ])
    })

    it('records nothing for a read that settles in time', async () => {
        await expect(withPanelLoadTimeout('scout_memory', async () => ['entry'])).resolves.toEqual(['entry'])

        jest.advanceTimersByTime(PANEL_LOAD_TIMEOUT_MS)

        expect(timeoutCaptures()).toEqual([])
    })
})
