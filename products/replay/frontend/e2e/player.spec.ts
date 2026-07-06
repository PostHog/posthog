import { PlaywrightWorkspaceSetupResult, expect, test } from '@playwright-utils/workspace-test-base'
import { Locator, Page } from '@playwright/test'

import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'

// The mock recording is ~12s across two browser windows; serving each window as its own
// blob_v2 source exercises multi-source loading, promotion, and cross-source seeks.
const SESSION_ID = recordingMetaJson.id
const [windowOneJSONL, windowTwoJSONL] = snapshotsAsJSONLines().trim().split('\n')

const SOURCES = [
    {
        source: 'blob_v2',
        blob_key: '0',
        start_timestamp: '2023-05-01T14:46:20.877000Z',
        end_timestamp: '2023-05-01T14:46:26.571000Z',
    },
    {
        source: 'blob_v2',
        blob_key: '1',
        start_timestamp: '2023-05-01T14:46:28.104000Z',
        end_timestamp: '2023-05-01T14:46:32.745000Z',
    },
]
const BLOBS: Record<string, string> = { '0': windowOneJSONL, '1': windowTwoJSONL }

async function mockRecordingApi(page: Page): Promise<void> {
    await page.route(
        new RegExp(`/api/environments/\\d+/session_recordings/${SESSION_ID}/snapshots/?(\\?.*)?$`),
        async (route) => {
            const url = new URL(route.request().url())
            // Content requests carry ?source=blob_v2 (+ a blob key range); listing requests don't.
            if (url.searchParams.get('source') === 'blob_v2') {
                const start = Number(url.searchParams.get('start_blob_key') ?? url.searchParams.get('blob_key') ?? 0)
                const end = Number(url.searchParams.get('end_blob_key') ?? start)
                const body =
                    Object.keys(BLOBS)
                        .filter((key) => Number(key) >= start && Number(key) <= end)
                        .map((key) => BLOBS[key])
                        .join('\n') + '\n'
                return route.fulfill({ status: 200, contentType: 'application/json', body })
            }
            return route.fulfill({ status: 200, json: { sources: SOURCES } })
        }
    )
    await page.route(new RegExp(`/api/environments/\\d+/session_recordings/${SESSION_ID}/?(\\?.*)?$`), (route) =>
        route.fulfill({ status: 200, json: recordingMetaJson })
    )
}

function playerFrame(page: Page): Locator {
    return page.locator('.PlayerFrame__content .replayer-wrapper iframe')
}

// The play/pause/rewind control is one button whose data-attr reflects player state. The
// controls chrome auto-hides, so state is asserted via the attribute (works while hidden)
// and the player is hovered right before any click to reveal the chrome.
function playPauseButton(page: Page): Locator {
    return page.locator('[data-attr=recording-play], [data-attr=recording-pause], [data-attr=recording-rewind]').first()
}

async function revealControls(page: Page): Promise<void> {
    await page.locator('.SessionRecordingPlayerWrapper').hover()
}

test.describe.configure({ mode: 'serial' })

test.describe('Session replay player', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
        await mockRecordingApi(page)
    })

    test('plays a multi-source recording, pauses, seeks, and reaches the end', async ({ page }) => {
        await test.step('boots and autoplays from the start', async () => {
            await page.goto(`/replay/${SESSION_ID}?t=0`)
            await expect(playerFrame(page)).toBeVisible({ timeout: 30000 })
            await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-pause')
            await expect(page.getByTestId('recording-timestamp')).toHaveText(/00:0[1-9]|00:1[01]/, { timeout: 15000 })
        })

        await test.step('pauses mid-playback', async () => {
            await revealControls(page)
            await page.locator('[data-attr=recording-pause]').click()
            await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-play')
        })

        await test.step('seeking backward while paused stays paused', async () => {
            await revealControls(page)
            await page.getByTestId('seek-skip-backward').click()
            await expect(page.getByTestId('recording-timestamp')).toHaveText(/00:00.*00:11/)
            await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-play')
            await expect(page.locator('.SessionRecordingPlayer--buffering')).not.toBeVisible()
        })

        await test.step('resumes and plays across both windows to the end', async () => {
            await revealControls(page)
            await page.locator('[data-attr=recording-play]').click()
            await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-pause')
            // Reaching the end proves playback advanced through both blob sources.
            await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-rewind', { timeout: 30000 })
        })

        await test.step('rewind at the end restarts playback from the start', async () => {
            await page.getByTestId('replay-overlay-rewind').click()
            await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-pause')
            await expect(page.getByTestId('recording-timestamp')).toHaveText(/00:0[0-5].*00:11/)
        })
    })

    test('deep link with ?t and ?pause renders a paused frame mid-recording', async ({ page }) => {
        await page.goto(`/replay/${SESSION_ID}?pause=true&t=9`)
        await expect(playerFrame(page)).toBeVisible({ timeout: 30000 })
        await expect(page.getByTestId('recording-timestamp')).toHaveText(/00:09.*00:11/)
        await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-play')
        await expect(page.locator('.SessionRecordingPlayer--buffering')).not.toBeVisible()
    })

    test('deep link past the end clamps to the last frame instead of buffering forever', async ({ page }) => {
        await page.goto(`/replay/${SESSION_ID}?pause=true&t=999`)
        await expect(playerFrame(page)).toBeVisible({ timeout: 30000 })
        await expect(page.getByTestId('recording-timestamp')).toHaveText(/00:11.*00:11/)
        await expect(page.getByTestId('replay-overlay-resume')).toBeAttached()
        await expect(page.locator('.SessionRecordingPlayer--buffering')).not.toBeVisible()
    })
})
