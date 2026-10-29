import { act, cleanup, renderHook } from '@testing-library/react-native'
import * as Updates from 'expo-updates'
import { AppState, type AppStateStatus, Keyboard, Platform } from 'react-native'

import { queryClient } from '@/api/queryClient'
import { captureError } from '@/lib/analytics'
import { withAppReloadBlocked } from '@/lib/appReload'

import { UPDATE_APPLY_AFTER_BACKGROUND_MS, UPDATE_CHECK_INTERVAL_MS, type UpdateSnapshot } from './automaticUpdates'
import { useAutomaticUpdates } from './useAutomaticUpdates'

let mockState: UpdateSnapshot
jest.mock('expo-updates', () => ({
    isEnabled: true,
    useUpdates: () => mockState,
    checkForUpdateAsync: jest.fn(),
    fetchUpdateAsync: jest.fn(),
    reloadAsync: jest.fn(),
}))
jest.mock('@/api/queryClient', () => ({ queryClient: { isMutating: jest.fn() } }))
jest.mock('@/lib/analytics', () => ({ captureError: jest.fn() }))

const originalDev = __DEV__

describe('mobile OTA lifecycle', () => {
    let appChange: (state: AppStateStatus) => void
    let remove: jest.Mock

    beforeEach(() => {
        jest.useFakeTimers({ now: Date.parse('2026-10-23T12:00:00Z') })
        jest.clearAllMocks()
        Object.defineProperty(globalThis, '__DEV__', { value: false, configurable: true })
        jest.replaceProperty(Platform, 'OS', 'ios')
        AppState.currentState = 'active'
        remove = jest.fn()
        jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, handler) => {
            appChange = handler
            return { remove }
        })
        jest.spyOn(Keyboard, 'isVisible').mockReturnValue(false)
        jest.mocked(queryClient.isMutating).mockReturnValue(0)
        jest.mocked(Updates.checkForUpdateAsync).mockResolvedValue({
            isAvailable: false,
            isRollBackToEmbedded: false,
        } as Updates.UpdateCheckResult)
        jest.mocked(Updates.fetchUpdateAsync).mockResolvedValue({
            isNew: true,
            isRollBackToEmbedded: false,
        } as Updates.UpdateFetchResult)
        jest.mocked(Updates.reloadAsync).mockResolvedValue(undefined)
        mockState = {
            isStartupProcedureRunning: false,
            isChecking: false,
            isDownloading: false,
            isRestarting: false,
            isUpdatePending: false,
        }
    })

    afterEach(() => {
        cleanup()
        Object.defineProperty(globalThis, '__DEV__', { value: originalDev, configurable: true })
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    async function changeAppState(state: AppStateStatus): Promise<void> {
        await act(async () => {
            AppState.currentState = state
            appChange(state)
            jest.advanceTimersByTime(1000)
        })
    }

    it('checks at launch, on foreground and during long sessions, then removes its timers and listener', async () => {
        const { unmount } = renderHook(() => useAutomaticUpdates(true))
        await act(async () => undefined)
        expect(Updates.checkForUpdateAsync).toHaveBeenCalledTimes(1)

        await changeAppState('background')
        await act(async () => jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS))
        expect(Updates.checkForUpdateAsync).toHaveBeenCalledTimes(1)

        jest.mocked(Updates.checkForUpdateAsync).mockResolvedValue({
            isAvailable: true,
            isRollBackToEmbedded: false,
        } as Updates.UpdateCheckResult)
        await changeAppState('active')
        expect(Updates.fetchUpdateAsync).toHaveBeenCalledTimes(1)
        expect(Updates.reloadAsync).not.toHaveBeenCalled()

        await changeAppState('background')
        await act(async () => jest.advanceTimersByTime(UPDATE_APPLY_AFTER_BACKGROUND_MS))
        await changeAppState('active')
        expect(Updates.reloadAsync).toHaveBeenCalledTimes(1)

        unmount()
        expect(remove).toHaveBeenCalledTimes(1)
    })

    it('polls while active and reports a failed check without preventing the next one', async () => {
        jest.mocked(Updates.checkForUpdateAsync).mockRejectedValueOnce(new Error('Offline'))
        const { unmount } = renderHook(() => useAutomaticUpdates(true))
        await act(async () => undefined)
        expect(captureError).toHaveBeenCalledWith(expect.objectContaining({ message: 'Offline' }))

        await act(async () => jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS))
        expect(Updates.checkForUpdateAsync).toHaveBeenCalledTimes(2)

        unmount()
        await act(async () => jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS))
        expect(Updates.checkForUpdateAsync).toHaveBeenCalledTimes(2)
    })

    it('cancels a scheduled foreground reload when the root unmounts', async () => {
        mockState.isUpdatePending = true
        const { unmount } = renderHook(() => useAutomaticUpdates(true))
        await changeAppState('background')
        await act(async () => jest.advanceTimersByTime(UPDATE_APPLY_AFTER_BACKGROUND_MS))
        act(() => {
            AppState.currentState = 'active'
            appChange('active')
        })
        unmount()
        await act(async () => jest.advanceTimersByTime(1000))
        expect(Updates.reloadAsync).not.toHaveBeenCalled()
    })

    it('checks again within 16 minutes when the native completion timestamp follows the original check', async () => {
        const { rerender } = renderHook(() => useAutomaticUpdates(true))
        await act(async () => undefined)
        jest.advanceTimersByTime(1000)
        mockState = { ...mockState, lastCheckForUpdateTimeSinceRestart: new Date() }
        rerender({})

        await act(async () => jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS))
        expect(Updates.checkForUpdateAsync).toHaveBeenCalledTimes(1)
        await act(async () => jest.advanceTimersByTime(60 * 1000))
        expect(Updates.checkForUpdateAsync).toHaveBeenCalledTimes(2)
    })

    it.each(['open chat or form', 'keyboard', 'mutation', 'pending operation'])(
        'defers a staged update while there is an %s and applies it on a later safe return',
        async (blocker) => {
            mockState.isUpdatePending = true
            jest.mocked(Keyboard.isVisible).mockReturnValue(blocker === 'keyboard')
            jest.mocked(queryClient.isMutating).mockReturnValue(blocker === 'mutation' ? 1 : 0)
            let finishOperation: (() => void) | undefined
            const operation =
                blocker === 'pending operation'
                    ? withAppReloadBlocked(
                          () =>
                              new Promise<void>((resolve) => {
                                  finishOperation = resolve
                              })
                      )
                    : Promise.resolve()
            const { rerender } = renderHook((props: { safe: boolean }) => useAutomaticUpdates(props.safe), {
                initialProps: { safe: blocker !== 'open chat or form' },
            })

            await changeAppState('background')
            await act(async () => jest.advanceTimersByTime(UPDATE_APPLY_AFTER_BACKGROUND_MS))
            await changeAppState('active')
            expect(Updates.reloadAsync).not.toHaveBeenCalled()

            finishOperation?.()
            await operation
            jest.mocked(Keyboard.isVisible).mockReturnValue(false)
            jest.mocked(queryClient.isMutating).mockReturnValue(0)
            rerender({ safe: true })
            expect(Updates.reloadAsync).not.toHaveBeenCalled()

            await changeAppState('background')
            await act(async () => jest.advanceTimersByTime(UPDATE_APPLY_AFTER_BACKGROUND_MS))
            await changeAppState('active')
            expect(Updates.reloadAsync).toHaveBeenCalledTimes(1)
        }
    )

    it('waits for native startup to finish before starting checks', async () => {
        mockState.isStartupProcedureRunning = true
        const { rerender } = renderHook(() => useAutomaticUpdates(true))
        await act(async () => undefined)
        expect(Updates.checkForUpdateAsync).not.toHaveBeenCalled()

        mockState = { ...mockState, isStartupProcedureRunning: false }
        rerender({})
        await act(async () => undefined)
        expect(Updates.checkForUpdateAsync).toHaveBeenCalledTimes(1)
    })

    it.each(['development', 'web', 'disabled'])('does not check or reload in %s', async (mode) => {
        if (mode === 'development') {
            Object.defineProperty(globalThis, '__DEV__', { value: true, configurable: true })
        } else if (mode === 'web') {
            jest.replaceProperty(Platform, 'OS', 'web')
        } else {
            jest.replaceProperty(Updates, 'isEnabled', false)
        }
        renderHook(() => useAutomaticUpdates(true))
        await act(async () => jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS))
        expect(Updates.checkForUpdateAsync).not.toHaveBeenCalled()
        expect(Updates.reloadAsync).not.toHaveBeenCalled()
        expect(AppState.addEventListener).not.toHaveBeenCalled()
    })
})
