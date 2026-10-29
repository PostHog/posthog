import type { UpdateCheckResult, UpdateFetchResult } from 'expo-updates'

import {
    AutomaticUpdates,
    UPDATE_APPLY_AFTER_BACKGROUND_MS,
    UPDATE_CHECK_INTERVAL_MS,
    type UpdateSnapshot,
} from './automaticUpdates'

const IDLE: UpdateSnapshot = {
    isStartupProcedureRunning: false,
    isChecking: false,
    isDownloading: false,
    isRestarting: false,
    isUpdatePending: false,
}
const PENDING: UpdateSnapshot = { ...IDLE, isUpdatePending: true }
const AVAILABLE = { isAvailable: true, isRollBackToEmbedded: false, manifest: { id: 'update-1' } } as UpdateCheckResult
const NO_UPDATE = { isAvailable: false, isRollBackToEmbedded: false } as UpdateCheckResult
const FETCHED = { isNew: true, isRollBackToEmbedded: false, manifest: { id: 'update-1' } } as UpdateFetchResult

function setup(): {
    updates: AutomaticUpdates
    client: {
        checkForUpdateAsync: jest.Mock<Promise<UpdateCheckResult>, []>
        fetchUpdateAsync: jest.Mock<Promise<UpdateFetchResult>, []>
        reloadAsync: jest.Mock<Promise<void>, []>
    }
} {
    const client = {
        checkForUpdateAsync: jest.fn<Promise<UpdateCheckResult>, []>().mockResolvedValue(AVAILABLE),
        fetchUpdateAsync: jest.fn<Promise<UpdateFetchResult>, []>().mockResolvedValue(FETCHED),
        reloadAsync: jest.fn<Promise<void>, []>().mockResolvedValue(undefined),
    }
    return { updates: new AutomaticUpdates(client), client }
}

describe('automatic OTA updates', () => {
    beforeEach(() => {
        jest.useFakeTimers({ now: Date.parse('2026-10-23T12:00:00Z') })
    })

    afterEach(() => jest.useRealTimers())

    it.each(['update', 'rollback'])('downloads a %s once and applies it on a later safe return', async (kind) => {
        const { updates, client } = setup()
        if (kind === 'rollback') {
            client.checkForUpdateAsync.mockResolvedValue({
                isAvailable: false,
                isRollBackToEmbedded: true,
                manifest: undefined,
                reason: undefined,
            })
            client.fetchUpdateAsync.mockResolvedValue({ isNew: false, isRollBackToEmbedded: true, manifest: undefined })
        }

        await updates.check(IDLE)
        expect(client.fetchUpdateAsync).toHaveBeenCalledTimes(1)
        expect(client.reloadAsync).not.toHaveBeenCalled()

        jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS)
        await updates.check(IDLE)
        expect(client.checkForUpdateAsync).toHaveBeenCalledTimes(1)

        updates.background()
        jest.advanceTimersByTime(UPDATE_APPLY_AFTER_BACKGROUND_MS)
        await updates.foreground(IDLE, true)
        await updates.foreground(IDLE, true)
        expect(client.reloadAsync).toHaveBeenCalledTimes(1)
    })

    it.each(['isStartupProcedureRunning', 'isChecking', 'isDownloading', 'isRestarting', 'isUpdatePending'] as const)(
        'leaves the native updater alone while %s',
        async (flag) => {
            const { updates, client } = setup()
            await updates.check({ ...IDLE, [flag]: true })
            expect(client.checkForUpdateAsync).not.toHaveBeenCalled()
            expect(client.fetchUpdateAsync).not.toHaveBeenCalled()
        }
    )

    it('throttles launch, foreground and timer checks including the native startup check', async () => {
        const { updates, client } = setup()
        client.checkForUpdateAsync.mockResolvedValue(NO_UPDATE)
        const state = { ...IDLE, lastCheckForUpdateTimeSinceRestart: new Date() }

        await updates.check(state)
        expect(client.checkForUpdateAsync).not.toHaveBeenCalled()
        jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS)
        await updates.foreground(state, true)
        await updates.check(state)
        expect(client.checkForUpdateAsync).toHaveBeenCalledTimes(1)
        expect(client.fetchUpdateAsync).not.toHaveBeenCalled()

        jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS)
        await updates.check(state)
        expect(client.checkForUpdateAsync).toHaveBeenCalledTimes(2)
    })

    it('does not overlap checks or downloads even when a request lasts longer than the check interval', async () => {
        const { updates, client } = setup()
        let finishCheck!: (result: UpdateCheckResult) => void
        let finishDownload!: (result: UpdateFetchResult) => void
        client.checkForUpdateAsync.mockReturnValue(
            new Promise((resolve) => {
                finishCheck = resolve
            })
        )
        client.fetchUpdateAsync.mockReturnValue(
            new Promise((resolve) => {
                finishDownload = resolve
            })
        )

        const downloading = updates.check(IDLE)
        jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS)
        await updates.foreground(IDLE, true)
        expect(client.checkForUpdateAsync).toHaveBeenCalledTimes(1)

        finishCheck(AVAILABLE)
        await Promise.resolve()
        updates.background()
        jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS)
        await updates.foreground(PENDING, true)
        expect(client.reloadAsync).not.toHaveBeenCalled()
        expect(client.fetchUpdateAsync).toHaveBeenCalledTimes(1)

        finishDownload(FETCHED)
        await downloading
        expect(client.reloadAsync).not.toHaveBeenCalled()
    })

    it.each(['checkForUpdateAsync', 'fetchUpdateAsync'] as const)(
        'retries after an offline failure in %s without a tight retry loop',
        async (operation) => {
            const { updates, client } = setup()
            client[operation].mockRejectedValueOnce(new Error('Offline'))
            await expect(updates.check(IDLE)).rejects.toThrow('Offline')
            await updates.foreground(IDLE, true)
            expect(client.checkForUpdateAsync).toHaveBeenCalledTimes(1)

            jest.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS)
            await updates.check(IDLE)
            expect(client.checkForUpdateAsync).toHaveBeenCalledTimes(2)
            expect(client.fetchUpdateAsync).toHaveBeenLastCalledWith()
            expect(client.reloadAsync).not.toHaveBeenCalled()
        }
    )

    it.each([
        { away: UPDATE_APPLY_AFTER_BACKGROUND_MS - 1, canReload: true, expected: 0 },
        { away: UPDATE_APPLY_AFTER_BACKGROUND_MS, canReload: false, expected: 0 },
        { away: UPDATE_APPLY_AFTER_BACKGROUND_MS, canReload: true, expected: 1 },
    ])('applies a native-staged update only on an eligible return: %j', async ({ away, canReload, expected }) => {
        const { updates, client } = setup()
        await updates.foreground(PENDING, true)
        expect(client.reloadAsync).not.toHaveBeenCalled()

        updates.background()
        jest.advanceTimersByTime(away)
        await updates.foreground(PENDING, canReload)
        expect(client.reloadAsync).toHaveBeenCalledTimes(expected)
        expect(client.checkForUpdateAsync).not.toHaveBeenCalled()
    })

    it('can apply a staged update on a later return after a reload fails', async () => {
        const { updates, client } = setup()
        client.reloadAsync.mockRejectedValueOnce(new Error('Reload failed'))
        updates.background()
        jest.advanceTimersByTime(UPDATE_APPLY_AFTER_BACKGROUND_MS)
        await expect(updates.foreground(PENDING, true)).rejects.toThrow('Reload failed')

        updates.background()
        jest.advanceTimersByTime(UPDATE_APPLY_AFTER_BACKGROUND_MS)
        await updates.foreground(PENDING, true)
        expect(client.reloadAsync).toHaveBeenCalledTimes(2)
    })
})
