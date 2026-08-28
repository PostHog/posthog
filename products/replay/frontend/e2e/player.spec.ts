import { PlaywrightWorkspaceSetupResult, expect, test } from '@playwright-utils/workspace-test-base'
import { Locator, Page } from '@playwright/test'
import snappy from 'snappyjs'

import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import {
    lateFullSnapshotAsJSONLines,
    snapshotsAsJSONLines,
} from 'scenes/session-recordings/__mocks__/recording_snapshots'

import { SessionRecordingType } from '~/types'

// The base mock recording is ~12s across two browser windows, and serving each window as its own blob_v2 source exercises multi-source loading, promotion, and cross-source seeks.
const SESSION_ID = recordingMetaJson.id
const [windowOneJSONL, windowTwoJSONL] = snapshotsAsJSONLines().trim().split('\n')
const BASE_TS = 1682952380877 // first event of windowOneJSONL, matches recordingMetaJson.start_time

interface MockRecording {
    meta: SessionRecordingType
    blobs: string[] // JSONL body per blob key ('0', '1', ...)
    delayMsByKey?: Record<string, number>
}

function isoAt(offsetMs: number): string {
    return new Date(BASE_TS + offsetMs).toISOString()
}

function metaVariant(id: string, durationMs: number): SessionRecordingType {
    return {
        ...recordingMetaJson,
        id,
        recording_duration: Math.floor(durationMs / 1000),
        start_time: isoAt(0),
        end_time: isoAt(durationMs),
    }
}

function shiftJSONLine(line: string, offsetMs: number): string {
    const parsed = JSON.parse(line)
    return JSON.stringify({
        window_id: parsed.window_id,
        data: parsed.data.map((e: { timestamp: number }) => ({ ...e, timestamp: e.timestamp + offsetMs })),
    })
}

function stripFullSnapshots(line: string): string {
    const parsed = JSON.parse(line)
    return JSON.stringify({
        window_id: parsed.window_id,
        data: parsed.data.filter((e: { type: number }) => e.type !== 2),
    })
}

function lastEventTimestamp(line: string): number {
    const parsed = JSON.parse(line)
    return parsed.data[parsed.data.length - 1].timestamp
}

const RECORDINGS: Record<string, MockRecording> = {
    // Two windows served as two blob sources.
    [SESSION_ID]: {
        meta: recordingMetaJson,
        blobs: [windowOneJSONL, windowTwoJSONL],
    },
    // Same two sources, but the second blob arrives late — forces buffering then recovery.
    [`${SESSION_ID}-slow`]: {
        meta: metaVariant(`${SESSION_ID}-slow`, lastEventTimestamp(windowTwoJSONL) - BASE_TS),
        blobs: [windowOneJSONL, windowTwoJSONL],
        delayMsByKey: { '1': 4000 },
    },
    // ~6s of activity, a 2-minute idle gap, then the same activity again.
    [`${SESSION_ID}-gap`]: {
        meta: metaVariant(`${SESSION_ID}-gap`, lastEventTimestamp(windowOneJSONL) - BASE_TS + 126000),
        blobs: [`${windowOneJSONL}\n${shiftJSONLine(windowOneJSONL, 126000)}`],
    },
    // The only full snapshot arrives 5s into the recording — seeks before it must clamp forward.
    [`${SESSION_ID}-late`]: {
        meta: metaVariant(`${SESSION_ID}-late`, 6000),
        blobs: [lateFullSnapshotAsJSONLines(BASE_TS, 5000).trim()],
    },
    // No full snapshot at all — the recording can never render.
    [`${SESSION_ID}-nofs`]: {
        meta: metaVariant(`${SESSION_ID}-nofs`, lastEventTimestamp(windowOneJSONL) - BASE_TS),
        blobs: [stripFullSnapshots(windowOneJSONL)],
    },
}

// Frame each blob's JSONL as a raw-Snappy block behind a 4-byte big-endian length, matching what recording-api serves for blob_v2.
function snappyBlocks(texts: string[]): Buffer {
    const parts: Buffer[] = []
    for (const text of texts) {
        const compressed = Buffer.from(snappy.compress(Buffer.from(text, 'utf-8')))
        const length = Buffer.alloc(4)
        length.writeUInt32BE(compressed.length, 0)
        parts.push(length, compressed)
    }
    return Buffer.concat(parts)
}

async function mockRecordingApi(page: Page): Promise<void> {
    for (const [sessionId, recording] of Object.entries(RECORDINGS)) {
        await page.route(
            new RegExp(`/api/environments/\\d+/session_recordings/${sessionId}/snapshots/?(\\?.*)?$`),
            async (route) => {
                const url = new URL(route.request().url())
                // Content requests carry ?source=blob_v2 (+ a blob key range); listing requests don't.
                if (url.searchParams.get('source') === 'blob_v2') {
                    const start = Number(
                        url.searchParams.get('start_blob_key') ?? url.searchParams.get('blob_key') ?? 0
                    )
                    const end = Number(url.searchParams.get('end_blob_key') ?? start)
                    const keys = recording.blobs
                        .map((_, i) => `${i}`)
                        .filter((k) => Number(k) >= start && Number(k) <= end)
                    const delay = Math.max(...keys.map((k) => recording.delayMsByKey?.[k] ?? 0), 0)
                    if (delay > 0) {
                        await new Promise((resolve) => setTimeout(resolve, delay))
                    }
                    // blob_v2 content is length-prefixed Snappy on the wire, which the player fetches with decompress=false and decompresses client-side.
                    return route.fulfill({
                        status: 200,
                        contentType: 'application/octet-stream',
                        body: snappyBlocks(keys.map((k) => recording.blobs[Number(k)])),
                    })
                }
                return route.fulfill({
                    status: 200,
                    json: {
                        sources: recording.blobs.map((blob, i) => {
                            const parsedFirst = JSON.parse(blob.split('\n')[0])
                            return {
                                source: 'blob_v2',
                                blob_key: `${i}`,
                                start_timestamp: new Date(parsedFirst.data[0].timestamp).toISOString(),
                                end_timestamp: new Date(lastEventTimestamp(blob.split('\n').at(-1)!)).toISOString(),
                            }
                        }),
                    },
                })
            }
        )
        await page.route(new RegExp(`/api/environments/\\d+/session_recordings/${sessionId}/?(\\?.*)?$`), (route) =>
            route.fulfill({ status: 200, json: recording.meta })
        )
    }
}

function playerFrame(page: Page): Locator {
    return page.locator('.PlayerFrame__content .replayer-wrapper iframe')
}

// One button whose data-attr reflects player state and stays assertable while the auto-hiding controls chrome is hidden (hover via revealControls before clicking it).
function playPauseButton(page: Page): Locator {
    return page.locator('[data-attr=recording-play], [data-attr=recording-pause], [data-attr=recording-rewind]').first()
}

async function revealControls(page: Page): Promise<void> {
    await page.locator('.SessionRecordingPlayerWrapper').hover()
}

// The buffering state class lands on both the player container and the "Buffering…" overlay text, so scope to the first match to avoid a strict-mode violation.
function bufferingIndicator(page: Page): Locator {
    return page.locator('.SessionRecordingPlayer--buffering').first()
}

async function scrubTo(page: Page, fraction: number): Promise<void> {
    await revealControls(page)
    const slider = page.locator('.PlayerSeekbar__slider')
    const box = (await slider.boundingBox())!
    await page.mouse.click(box.x + box.width * fraction, box.y + box.height / 2)
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

    test('plays a multi-source recording, pauses, seeks, scrubs, and reaches the end', async ({ page }) => {
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
            await expect(bufferingIndicator(page)).not.toBeVisible()
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

        await test.step('scrubbing into the second window while playing keeps playing', async () => {
            await scrubTo(page, 0.8)
            await expect(page.getByTestId('recording-timestamp')).toHaveText(/00:0[89]|00:1[01]/)
            await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-pause')
            // ...and end detection still works after a scrub.
            await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-rewind', { timeout: 15000 })
        })
    })

    test('deep link with ?t and ?pause renders a paused frame mid-recording', async ({ page }) => {
        await page.goto(`/replay/${SESSION_ID}?pause=true&t=9`)
        await expect(playerFrame(page)).toBeVisible({ timeout: 30000 })
        await expect(page.getByTestId('recording-timestamp')).toHaveText(/00:09.*00:11/)
        await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-play')
        await expect(bufferingIndicator(page)).not.toBeVisible()
    })

    test('deep link past the end clamps to the last frame instead of buffering forever', async ({ page }) => {
        await page.goto(`/replay/${SESSION_ID}?pause=true&t=999`)
        await expect(playerFrame(page)).toBeVisible({ timeout: 30000 })
        await expect(page.getByTestId('recording-timestamp')).toHaveText(/00:11.*00:11/)
        await expect(page.getByTestId('replay-overlay-resume')).toBeAttached()
        await expect(bufferingIndicator(page)).not.toBeVisible()
    })

    test('fast-forwards through long inactivity and resumes normal playback', async ({ page }) => {
        await page.goto(`/replay/${SESSION_ID}-gap?t=0`)
        await expect(playerFrame(page)).toBeVisible({ timeout: 30000 })
        await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-pause')
        // ~6s of activity precede the 2-minute gap; skipping plays the gap at >=50x.
        await expect(page.getByText('Skipping inactivity')).toBeVisible({ timeout: 20000 })
        await expect(page.getByTestId('recording-timestamp')).toHaveText(/02:0[6-9]|02:1[0-9]/, { timeout: 20000 })
        await expect(playPauseButton(page)).toHaveAttribute('data-attr', 'recording-pause')
    })

    test('seeking before a late full snapshot clamps forward to the first renderable frame', async ({ page }) => {
        await page.goto(`/replay/${SESSION_ID}-late?pause=true&t=0`)
        await expect(playerFrame(page)).toBeVisible({ timeout: 30000 })
        await expect(page.getByTestId('recording-timestamp')).toHaveText(/00:05.*00:06/)
        await expect(bufferingIndicator(page)).not.toBeVisible()
    })

    test('a recording with no full snapshot shows a terminal error instead of buffering', async ({ page }) => {
        await page.goto(`/replay/${SESSION_ID}-nofs?pause=true&t=0`)
        await expect(page.getByRole('heading', { name: "This recording can't be played" })).toBeVisible({
            timeout: 30000,
        })
        await expect(bufferingIndicator(page)).not.toBeVisible()
    })

    test('buffers while a source is still loading and recovers when it arrives', async ({ page }) => {
        await page.goto(`/replay/${SESSION_ID}-slow?pause=true&t=9`)
        // The target position lives in the delayed second source, so the player must buffer first...
        await expect(bufferingIndicator(page)).toBeVisible({ timeout: 15000 })
        // ...and render the requested frame once the source lands, without manual intervention.
        await expect(playerFrame(page)).toBeVisible({ timeout: 30000 })
        await expect(page.getByTestId('recording-timestamp')).toHaveText(/00:09.*00:11/)
        await expect(bufferingIndicator(page)).not.toBeVisible()
    })
})
