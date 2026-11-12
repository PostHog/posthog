import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'
import { AppState } from 'react-native'

import type { ExperimentApi, ExperimentResultsRunApi } from '@/api/experiments'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'

import { useRecalculation } from './detailHooks'

const mockSource = {
    startRecalculation: jest.fn(),
    fetchResultsRun: jest.fn(),
    fetchLatestResults: jest.fn(),
}

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
// A getter, because the factory runs before `mockSource` is initialized.
jest.mock('@/demo/experiments', () => ({
    get demoExperimentsSource() {
        return mockSource
    },
}))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))
jest.mock('expo-router', () => ({
    useFocusEffect: (callback: () => void) => require('react').useEffect(callback, [callback]),
}))

const EXPERIMENT = {
    id: 7,
    name: 'Checkout button copy',
    feature_flag_key: 'checkout-button-copy',
    start_date: '2026-11-01T00:00:00Z',
    status: 'running',
} as unknown as ExperimentApi

const LATEST = { id: 'run-0', results: [], query_to: '2026-11-12T02:00:00Z' } as unknown as ExperimentResultsRunApi

function setup(): { result: { current: ReturnType<typeof useRecalculation> }; notices: string[]; unmount: () => void } {
    const notices: string[] = []
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const hook = renderHook(() => useRecalculation(EXPERIMENT, LATEST, 'running', (text) => notices.push(text)), {
        wrapper,
    })
    return { result: hook.result, notices, unmount: hook.unmount }
}

describe('useRecalculation', () => {
    beforeAll(async () => {
        await useDemoMode.persist.rehydrate()
    })

    beforeEach(() => {
        AppState.currentState = 'active'
        useDemoMode.setState({ enabled: true })
        jest.mocked(track).mockClear()
        mockSource.fetchLatestResults.mockResolvedValue(LATEST)
    })

    it('counts down the server window after a 429 instead of starting a run', async () => {
        mockSource.startRecalculation.mockResolvedValue({ run: null, retryAfterMs: 252_000 })
        const { result, unmount } = setup()
        await waitFor(() => expect(result.current.phase.kind).toBe('idle'))
        const before = Date.now()
        act(() => result.current.onPull())
        await waitFor(() => expect(result.current.pulling).toBe(false))
        const phase = result.current.phase
        expect(phase.kind).toBe('window')
        expect(phase.kind === 'window' ? phase.retryAt - before : 0).toBeGreaterThanOrEqual(252_000)
        expect(mockSource.fetchResultsRun).not.toHaveBeenCalled()
        expect(track).toHaveBeenCalledWith('mobile_experiment_results_refreshed', { outcome: 'window' })
        unmount()
    })

    it('follows a started run until it completes, then marks the results as this phone’s refresh', async () => {
        mockSource.startRecalculation.mockResolvedValue({
            run: { id: 'run-1', status: 'pending', total_metrics: 3, completed_metrics: 0, is_existing: false },
            retryAfterMs: null,
        })
        mockSource.fetchResultsRun.mockResolvedValue({
            id: 'run-1',
            status: 'completed',
            total_metrics: 3,
            completed_metrics: 3,
            failed_metrics: 0,
            results: [],
        })
        const { result, notices, unmount } = setup()
        await waitFor(() => expect(result.current.phase.kind).toBe('idle'))
        act(() => result.current.onPull())
        await waitFor(() => expect(mockSource.fetchResultsRun).toHaveBeenCalledWith(7, 'run-1', expect.anything()))
        await waitFor(() => expect(result.current.phase.kind).toBe('idle'))
        expect(result.current.mineRunId).toBe('run-1')
        expect(notices).toEqual([])
        expect(track).toHaveBeenCalledWith('mobile_experiment_results_refreshed', { outcome: 'started' })
        unmount()
    })
})
