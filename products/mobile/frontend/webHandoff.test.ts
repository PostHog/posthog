/** @jest-environment jsdom */
import { URL as NodeURL, URLSearchParams as NodeURLSearchParams } from 'node:url'

import { HANDOFF_PARAM, handoffMarker, takeHandoff } from './handoffProtocol'
import { consumeMobileHandoff, installMobileHandoff } from './webHandoff'

const ID = '00000000-0000-4000-8000-000000000001'
const NOW = 1_800_000_000_000

describe('web handoff', () => {
    beforeAll(() => {
        global.URL = NodeURL as typeof URL
        global.URLSearchParams = NodeURLSearchParams as typeof URLSearchParams
    })
    beforeEach(() => {
        jest.useFakeTimers().setSystemTime(NOW)
        window.history.replaceState({}, '', '/')
        Object.defineProperty(window.crypto, 'randomUUID', { value: () => ID, configurable: true })
    })
    afterEach(() => {
        document.body.innerHTML = ''
        jest.useRealTimers()
    })

    it('removes inbound metadata before analytics initialization and waits for the opt-in flag', () => {
        window.history.replaceState(
            {},
            '',
            `/project/2/insights/abc?x=1#tab=events&${HANDOFF_PARAM}=${handoffMarker(ID, NOW)}`
        )
        const id = consumeMobileHandoff()
        expect(id).toBe(ID)
        expect(window.location.hash).toBe('#tab=events')
        expect(window.location.search).toBe('?x=1')
        let flagsChanged: () => void = () => undefined
        const client = {
            capture: jest.fn(),
            isFeatureEnabled: jest.fn(() => false),
            onFeatureFlags: jest.fn((fn: () => void) => {
                flagsChanged = fn
                return jest.fn()
            }),
        }
        const cleanup = installMobileHandoff(client, id)
        expect(client.capture).not.toHaveBeenCalled()
        client.isFeatureEnabled.mockReturnValue(true)
        flagsChanged()
        flagsChanged()
        expect(client.capture).toHaveBeenCalledTimes(1)
        expect(client.capture).toHaveBeenCalledWith('web_session_handoff_received', {
            handoff_id: ID,
            session_continuity: 'correlated',
        })
        cleanup()
    })

    it.each([
        ['posthog-dev://report/example', true],
        ['posthog-preview://inbox', true],
        ['posthog-dev://callback?code=fake', false],
        ['posthog://inbox', false],
        ['https://example.com/inbox', false],
        ['posthog-dev://inbox#tab=all', false],
    ])('instruments only internal navigation anchors: %s', (href, decorated) => {
        const client = { capture: jest.fn(), isFeatureEnabled: () => true, onFeatureFlags: () => () => undefined }
        const cleanup = installMobileHandoff(client, null)
        const preventNavigation = (event: MouseEvent): void => event.preventDefault()
        window.addEventListener('click', preventNavigation)
        const anchor = document.createElement('a')
        anchor.href = href
        document.body.append(anchor)
        anchor.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }))
        expect(takeHandoff(new URL(anchor.href), NOW)).toBe(decorated ? ID : null)
        expect(client.capture).toHaveBeenCalledTimes(decorated ? 1 : 0)
        cleanup()
        anchor.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }))
        expect(client.capture).toHaveBeenCalledTimes(decorated ? 1 : 0)
        window.removeEventListener('click', preventNavigation)
    })
})
