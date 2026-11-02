import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { AppState, type AppStateStatus } from 'react-native'

import { fetchReportPullRequestChecks } from '@/api/reports'

import { CHECKS_POLL_INTERVAL_MS, pullRequestChecksStatus, usePullRequestChecks } from './usePullRequestChecks'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-notifications', () => ({}))
jest.mock('expo-router', () => ({
    useFocusEffect: (callback: () => void) => require('react').useEffect(callback, [callback]),
}))
jest.mock('@/auth/useProjectScope', () => ({
    useProjectScope: () => ({ host: 'https://app.example.com', projectId: 2 }),
}))
jest.mock('@/demo/demoMode', () => ({ useDataMode: () => 'live' }))
jest.mock('@/api/reports', () => ({
    ...jest.requireActual('@/api/reports'),
    fetchReportPullRequestChecks: jest.fn(),
}))

function check(
    status: string | null,
    conclusion: string | null
): { name: string; status: string | null; conclusion: string | null; url: null } {
    return { name: 'tests', status, conclusion, url: null }
}

const PASS = { checks: [check('completed', 'success')] }
const FAIL = { checks: [check('completed', 'failure')] }

describe('selected pull request checks', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.clearAllMocks()
        AppState.currentState = 'active'
        jest.spyOn(AppState, 'addEventListener').mockReturnValue({ remove: () => undefined })
    })

    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    test.each([
        ['missing response', undefined, 'unavailable'],
        ['empty checks', [], 'none'],
        ['passed checks', PASS.checks, 'passing'],
        ['failed checks', FAIL.checks, 'failing'],
        ['checks running', [check('in_progress', null)], 'pending'],
        ['unknown conclusion', [check('completed', null)], 'unavailable'],
        ['malformed check', [{}], 'unavailable'],
        ['failure with other checks pending', [...FAIL.checks, check('queued', null)], 'failing'],
    ])('%s', (_name, checks, expected) => {
        expect(pullRequestChecksStatus(checks)).toBe(expected)
    })

    test('loads only the selected canonical PR, never borrows another PR success, and stops while hidden', async () => {
        let appChange!: (state: AppStateStatus) => void
        jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, handler) => {
            appChange = handler
            return { remove: () => undefined }
        })
        jest.mocked(fetchReportPullRequestChecks).mockResolvedValue(PASS)
        const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
        )
        const { result, rerender, unmount } = renderHook(
            ({ id, visible }: { id: string | undefined; visible: boolean }) =>
                usePullRequestChecks('report-1', id, visible),
            { wrapper, initialProps: { id: undefined as string | undefined, visible: true } }
        )
        try {
            await act(async () => {
                await jest.advanceTimersByTimeAsync(10)
            })
            expect(fetchReportPullRequestChecks).not.toHaveBeenCalled()
            expect(result.current.status).toBe('unavailable')
            rerender({ id: 'canonical-pr-one', visible: true })
            await act(async () => {
                await jest.advanceTimersByTimeAsync(10)
            })
            expect(result.current.status).toBe('passing')
            expect(result.current.observedAt).toEqual(expect.any(Number))
            expect(fetchReportPullRequestChecks).toHaveBeenLastCalledWith(
                'report-1',
                'canonical-pr-one',
                expect.any(AbortSignal)
            )
            jest.mocked(fetchReportPullRequestChecks).mockRejectedValue(new Error('checks unavailable'))
            rerender({ id: 'canonical-pr-two', visible: true })
            expect(result.current.status).toBe('checking')
            await act(async () => {
                await jest.advanceTimersByTimeAsync(10)
            })
            expect(result.current.status).toBe('unavailable')
            expect(result.current.observedAt).toBeUndefined()
            jest.mocked(fetchReportPullRequestChecks).mockResolvedValue(FAIL)
            await act(async () => {
                await jest.advanceTimersByTimeAsync(CHECKS_POLL_INTERVAL_MS)
            })
            expect(result.current.status).toBe('failing')
            await act(async () => {
                appChange('background')
            })
            const beforeBackground = jest.mocked(fetchReportPullRequestChecks).mock.calls.length
            await act(async () => {
                await jest.advanceTimersByTimeAsync(CHECKS_POLL_INTERVAL_MS * 2)
            })
            expect(fetchReportPullRequestChecks).toHaveBeenCalledTimes(beforeBackground)
            await act(async () => {
                appChange('active')
                await jest.advanceTimersByTimeAsync(10)
            })
            expect(fetchReportPullRequestChecks).toHaveBeenCalledTimes(beforeBackground + 1)
            rerender({ id: 'canonical-pr-two', visible: false })
            const beforeHidden = jest.mocked(fetchReportPullRequestChecks).mock.calls.length
            await act(async () => {
                await jest.advanceTimersByTimeAsync(CHECKS_POLL_INTERVAL_MS * 2)
            })
            expect(fetchReportPullRequestChecks).toHaveBeenCalledTimes(beforeHidden)
        } finally {
            unmount()
            client.clear()
        }
    })
})
