import { Linking } from 'react-native'
import { useAuthStore } from '@/auth/authStore'
import { redirectSystemPath } from '../../app/+native-intent'

import { setAnalyticsClient } from './analytics'
import { HANDOFF_PARAM, handoffId, handoffMarker, takeHandoff } from './handoffProtocol'
import { openPostHogUrl, receiveSessionHandoff } from './sessionHandoff'

jest.mock('@/auth/authStore', () => ({ useAuthStore: { getState: jest.fn() } }))
jest.mock('./environment', () => ({ isInternalBuild: true }))
jest.mock('expo-crypto', () => ({ randomUUID: () => '00000000-0000-4000-8000-000000000001' }))

const ID = '00000000-0000-4000-8000-000000000001'
const NOW = 1_800_000_000_000

describe('session handoff', () => {
    const capture = jest.fn()
    const identify = jest.fn()
    const reset = jest.fn()
    beforeEach(() => {
        jest.useFakeTimers().setSystemTime(NOW)
        jest.clearAllMocks()
        process.env.EXPO_PUBLIC_POSTHOG_HANDOFF = '1'
        setAnalyticsClient({ capture, identify, reset })
        jest.mocked(useAuthStore.getState).mockReturnValue({
            status: 'signed_in',
            host: 'https://us.posthog.com',
            projectId: 2,
        } as ReturnType<typeof useAuthStore.getState>)
        jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
    })
    afterEach(() => {
        setAnalyticsClient(null)
        delete process.env.EXPO_PUBLIC_POSTHOG_HANDOFF
        jest.useRealTimers()
    })

    it('correlates a same-host project navigation without copying identity or session state', async () => {
        await openPostHogUrl('https://us.posthog.com/project/2/insights/abc')
        const url = new URL(jest.mocked(Linking.openURL).mock.calls[0]?.[0] ?? 'https://example.com')
        expect(takeHandoff(url, NOW)).toBe(ID)
        expect(capture).toHaveBeenCalledWith('mobile_session_handoff_started', {
            handoff_id: ID,
            session_continuity: 'correlated',
        })
        expect(identify).not.toHaveBeenCalled()
        expect(reset).not.toHaveBeenCalled()
    })

    it.each([
        'https://example.com/project/2/insights/abc',
        'https://eu.posthog.com/project/2/insights/abc',
        'https://us.posthog.com/project/3/insights/abc',
        'https://us.posthog.com/oauth/authorize',
        'https://us.posthog.com/project/2/insights/abc#tab=events',
        'https://name:password@us.posthog.com/project/2/insights/abc',
        'http://us.posthog.com/project/2/insights/abc',
        'invalid-url',
    ])('does not decorate %s', async (url) => {
        await openPostHogUrl(url)
        expect(Linking.openURL).toHaveBeenCalledWith(url)
        expect(capture).not.toHaveBeenCalled()
    })

    it('leaves navigation unchanged when disabled', async () => {
        delete process.env.EXPO_PUBLIC_POSTHOG_HANDOFF
        const url = 'https://us.posthog.com/project/2/insights/abc'
        await openPostHogUrl(url)
        expect(Linking.openURL).toHaveBeenCalledWith(url)
        expect(capture).not.toHaveBeenCalled()
    })

    it('receives a native link, strips only the marker, and leaves authentication alone', () => {
        const url = redirectSystemPath({
            path: `posthog-dev://inbox#tab=all&${HANDOFF_PARAM}=${handoffMarker(ID, NOW)}`,
            initial: true,
        })
        expect(url).toBe('posthog-dev://inbox#tab=all')
        expect(capture).toHaveBeenCalledWith('mobile_session_handoff_received', {
            handoff_id: ID,
            session_continuity: 'correlated',
        })
        expect(identify).not.toHaveBeenCalled()
        expect(reset).not.toHaveBeenCalled()
    })

    it.each([
        ['https://us.posthog.com/project/2/replay/example-session?t=12', '/replay/example-session?source=link&t=12'],
        ['https://us.posthog.com/project/2/error_tracking/example-issue', '/errors/example-issue?from=link'],
        ['posthog-dev://callback?code=example-code', null],
    ])('preserves native routing for %s', (path, target) => {
        expect(redirectSystemPath({ path, initial: false })).toBe(target)
        expect(capture).not.toHaveBeenCalledWith('mobile_session_handoff_received', expect.anything())
    })

    it.each([-120_001, 1])('rejects expired or future markers (%s ms)', (offset) => {
        expect(handoffId(handoffMarker(ID, NOW + offset), NOW)).toBeNull()
    })

    it.each(['not-a-uuid', `${ID}.${NOW}.extra`, `${ID}.NaN`])('rejects malformed marker %s', (marker) => {
        expect(handoffId(marker, NOW)).toBeNull()
    })

    it('rejects and removes duplicate markers', () => {
        const marker = handoffMarker(ID, NOW)
        const url = new URL(`posthog-dev://inbox#${HANDOFF_PARAM}=${marker}&${HANDOFF_PARAM}=${marker}`)
        expect(takeHandoff(url, NOW)).toBeNull()
        expect(url.hash).toBe('')
    })

    it.each(['posthog-dev://callback?code=fake', 'posthog://inbox', 'https://example.com/inbox'])(
        'does not handle %s',
        (path) => {
            const url = `${path}#${HANDOFF_PARAM}=${handoffMarker(ID, NOW)}`
            expect(receiveSessionHandoff(url)).toBe(url)
            expect(capture).not.toHaveBeenCalled()
        }
    )
})
