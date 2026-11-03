import type { UpdateCheckResult, UpdateFetchResult, UseUpdatesReturnType } from 'expo-updates'

export const UPDATE_CHECK_INTERVAL_MS = 15 * 60 * 1000
export const UPDATE_APPLY_AFTER_BACKGROUND_MS = 5 * 60 * 1000

export type UpdateSnapshot = Pick<
    UseUpdatesReturnType,
    | 'isStartupProcedureRunning'
    | 'isChecking'
    | 'isDownloading'
    | 'isRestarting'
    | 'isUpdatePending'
    | 'lastCheckForUpdateTimeSinceRestart'
>

interface UpdateClient {
    checkForUpdateAsync: () => Promise<UpdateCheckResult>
    fetchUpdateAsync: () => Promise<UpdateFetchResult>
    reloadAsync: () => Promise<void>
}

export class AutomaticUpdates {
    private inFlight = false
    private downloaded = false
    private reloading = false
    private lastCheckAt: number | null = null
    private backgroundedAt: number | null = null

    constructor(private readonly client: UpdateClient) {}

    private busy(state: UpdateSnapshot): boolean {
        return (
            this.inFlight ||
            this.reloading ||
            state.isStartupProcedureRunning ||
            state.isChecking ||
            state.isDownloading ||
            state.isRestarting
        )
    }

    async check(state: UpdateSnapshot): Promise<void> {
        if (this.busy(state) || this.downloaded || state.isUpdatePending) {
            return
        }
        const now = Date.now()
        const lastCheckAt = Math.max(
            this.lastCheckAt ?? -Infinity,
            state.lastCheckForUpdateTimeSinceRestart?.getTime() ?? -Infinity
        )
        if (now - lastCheckAt < UPDATE_CHECK_INTERVAL_MS) {
            return
        }
        this.lastCheckAt = now
        this.inFlight = true
        try {
            const update = await this.client.checkForUpdateAsync()
            if (update.isAvailable || update.isRollBackToEmbedded) {
                const fetched = await this.client.fetchUpdateAsync()
                this.downloaded = fetched.isNew || fetched.isRollBackToEmbedded
            }
        } finally {
            this.inFlight = false
        }
    }

    background(): void {
        this.backgroundedAt ??= Date.now()
    }

    async foreground(state: UpdateSnapshot, canReload: boolean): Promise<void> {
        const backgroundedAt = this.backgroundedAt
        this.backgroundedAt = null
        if (
            backgroundedAt !== null &&
            Date.now() - backgroundedAt >= UPDATE_APPLY_AFTER_BACKGROUND_MS &&
            canReload &&
            (this.downloaded || state.isUpdatePending) &&
            !this.busy(state)
        ) {
            this.reloading = true
            try {
                await this.client.reloadAsync()
            } catch (error) {
                this.reloading = false
                throw error
            }
            return
        }
        await this.check(state)
    }
}
