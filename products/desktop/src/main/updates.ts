/**
 * Auto-updates via electron-updater.
 *
 * The feed is the latest GitHub release's assets (`publish` in
 * electron-builder.yml, baked into the packaged app as app-update.yml):
 * latest-mac.yml / latest.yml describe the newest version, and the artifacts
 * are downloaded from the same releases/latest/download base URL.
 *
 * Behavior: check shortly after launch and every few hours, download in the
 * background, install silently on quit (autoInstallOnAppQuit) — with a single
 * "Restart now?" prompt per downloaded version for users who want it sooner.
 * Background checks fail silently (offline, rate limits, unsigned dev builds);
 * only the explicit "Check for updates…" menu action surfaces errors.
 */

import { app, dialog } from 'electron'
import { autoUpdater } from 'electron-updater'

const FIRST_CHECK_DELAY_MS = 15_000
const CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000

export function isAutoUpdateEnabled(): boolean {
    // Dev builds have no app-update.yml (and macOS ad-hoc signatures can't be
    // updated by Squirrel anyway); the env var is the kill switch for packaged
    // builds during debugging.
    return app.isPackaged && !process.env.POSTHOG_DESKTOP_DISABLE_UPDATES
}

export class AppUpdater {
    private checking = false
    private userInitiated = false
    private promptedVersion: string | null = null
    readonly enabled = isAutoUpdateEnabled()

    start(): void {
        if (!this.enabled) {
            return
        }

        autoUpdater.logger = console
        autoUpdater.autoDownload = true
        autoUpdater.autoInstallOnAppQuit = true

        autoUpdater.on('update-available', (info) => {
            if (this.userInitiated) {
                void dialog.showMessageBox({
                    type: 'info',
                    message: `PostHog ${info.version} is available`,
                    detail: 'The update is downloading in the background. You will be asked to restart once it is ready.',
                })
            }
        })
        autoUpdater.on('update-not-available', () => {
            if (this.userInitiated) {
                void dialog.showMessageBox({
                    type: 'info',
                    message: 'You are up to date',
                    detail: `PostHog ${app.getVersion()} is the latest version.`,
                })
            }
        })
        autoUpdater.on('update-downloaded', (info) => {
            // Prompt once per version; declining still installs on next quit
            if (this.promptedVersion === info.version) {
                return
            }
            this.promptedVersion = info.version
            void dialog
                .showMessageBox({
                    type: 'info',
                    message: `PostHog ${info.version} is ready to install`,
                    detail: 'Restart now to update, or keep working — the update installs the next time you quit.',
                    buttons: ['Restart now', 'Later'],
                    defaultId: 0,
                    cancelId: 1,
                })
                .then(({ response }) => {
                    if (response === 0) {
                        autoUpdater.quitAndInstall()
                    }
                })
        })
        autoUpdater.on('error', (error) => {
            if (this.userInitiated) {
                dialog.showErrorBox('Update check failed', `${error?.message ?? error}`)
            } else {
                console.warn('Background update check failed:', `${error?.message ?? error}`)
            }
        })

        setTimeout(() => void this.check(false), FIRST_CHECK_DELAY_MS)
        setInterval(() => void this.check(false), CHECK_INTERVAL_MS)
    }

    /** "Check for updates…" menu action: same flow, but with dialogs on every outcome. */
    checkInteractively(): void {
        if (!this.enabled) {
            dialog.showErrorBox(
                'Updates unavailable',
                'Automatic updates only work in the packaged app. Download releases from posthogondesktop.com.'
            )
            return
        }
        void this.check(true)
    }

    private async check(userInitiated: boolean): Promise<void> {
        if (this.checking) {
            return
        }
        this.checking = true
        this.userInitiated = userInitiated
        try {
            await autoUpdater.checkForUpdates()
        } catch {
            // Reported via the 'error' listener above
        } finally {
            this.checking = false
            this.userInitiated = false
        }
    }
}
