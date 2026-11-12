import { isRecord } from '@/lib/records'

import {
    ApiError,
    apiJson,
    apiReadResponse,
    apiUrl,
    authorizationHeaders,
    NotSignedInError,
    projectPath,
} from './client'
import { missingScope } from './scopeErrors'
import { serverNow } from './serverClock'
import { TransportError, transport } from './transport'

// Shapes follow `ExportedAssetSerializer` in `products/exports/backend/api/exports.py`, keeping the fields the app reads.
// A finished render writes its output fields into `export_context`: `renderOutputFields` in
// `nodejs/src/session-replay/recording-rasterizer/postprocess.ts`.

export const REPLAY_VIDEO_FORMAT = 'video/mp4'

/** The web app refuses longer recordings too: the rasterizer cannot render them within its time budget. */
export const MAX_REPLAY_VIDEO_SECONDS = 3 * 60 * 60

/** `RASTERIZE_WORKFLOW_TIMEOUT`. A render older than this without content is dead, and the server marks it failed. */
export const REPLAY_VIDEO_RENDER_TIMEOUT_MS = 75 * 60_000

export interface ReplayVideoInactivityPeriod {
    /** Seconds from the start of the recording. */
    ts_from_s: number
    ts_to_s: number | null
    active: boolean
    /** Seconds into the video file. Both are the frame where playback resumed for a stretch the render skipped. */
    recording_ts_from_s?: number
    recording_ts_to_s?: number
}

export interface ReplayVideoExportContext {
    session_recording_id?: string
    timestamp?: number
    duration?: number
    width?: number
    height?: number
    filename?: string
    video_duration_s?: number
    playback_speed?: number
    truncated?: boolean
    file_size_bytes?: number
    inactivity_periods?: ReplayVideoInactivityPeriod[]
}

export interface ReplayVideoExport {
    id: number
    export_format: string
    created_at: string
    has_content: boolean
    export_context: ReplayVideoExportContext | null
    filename: string
    expires_after: string | null
    /** The server also sets this on a render that died without reporting a reason. */
    exception: string | null
}

/** What the player loads. Headers are present only when the API serves the bytes itself. */
export interface ReplayVideoSource {
    uri: string
    expiresAt?: number
    headers?: Record<string, string>
}

export type ReplayVideoErrorKind =
    | 'too_long'
    | 'limit_reached'
    | 'render_failed'
    | 'expired'
    | 'missing_scope'
    | 'signed_out'
    | 'network'
    | 'unknown'

const MESSAGES: Record<ReplayVideoErrorKind, string> = {
    too_long: 'This recording is longer than 3 hours, which is too long to play as one video.',
    limit_reached: 'Your team has reached its monthly limit for video exports.',
    render_failed: "Couldn't prepare this video. Try again.",
    expired: 'This video has expired. Prepare it again.',
    missing_scope:
        "Video playback needs a permission this app doesn't have yet. Ask an admin to update the app's registration, then sign in again.",
    signed_out: 'Sign in to continue.',
    network: 'Check your connection and try again.',
    unknown: "Couldn't prepare this video. Try again.",
}

const RATE_LIMITED_MESSAGE = 'Too many requests. Try again in a minute.'

export class ReplayVideoError extends Error {
    readonly kind: ReplayVideoErrorKind

    constructor(kind: ReplayVideoErrorKind, message: string = MESSAGES[kind]) {
        super(message)
        this.name = 'ReplayVideoError'
        this.kind = kind
    }
}

export function toReplayVideoError(error: unknown): ReplayVideoError {
    if (error instanceof ReplayVideoError) {
        return error
    }
    if (error instanceof NotSignedInError) {
        return new ReplayVideoError('signed_out')
    }
    if (error instanceof TransportError) {
        return new ReplayVideoError('network', error.message)
    }
    if (error instanceof ApiError) {
        if (missingScope(error) !== null) {
            return new ReplayVideoError('missing_scope')
        }
        const limit = exportLimitMessage(error)
        if (limit !== null) {
            return new ReplayVideoError('limit_reached', limit || undefined)
        }
        if (error.status === 401) {
            return new ReplayVideoError('signed_out')
        }
        if (error.status === 404) {
            return new ReplayVideoError('expired')
        }
        if (error.status === 429) {
            return new ReplayVideoError('network', RATE_LIMITED_MESSAGE)
        }
    }
    return new ReplayVideoError('unknown')
}

/** True for a failure that the next poll can get past: no connection, a rate limit, or a server error. */
export function isTransientReplayVideoError(error: unknown): boolean {
    return (
        error instanceof TransportError || (error instanceof ApiError && (error.status === 429 || error.status >= 500))
    )
}

/** The server's own words for the monthly cap, an empty string when it sent none, or null for any other error. */
function exportLimitMessage(error: ApiError): string | null {
    if (error.status !== 400 || !isRecord(error.body) || !('export_limit_exceeded' in error.body)) {
        return null
    }
    const reasons = error.body.export_limit_exceeded
    const first = Array.isArray(reasons) ? reasons[0] : reasons
    return typeof first === 'string' ? first : ''
}

function nullableString(value: unknown): string | null | undefined {
    if (value === null || value === undefined) {
        return null
    }
    return typeof value === 'string' ? value : undefined
}

function parseExport(value: unknown): ReplayVideoExport | null {
    if (!isRecord(value)) {
        return null
    }
    const { id, export_format, created_at, has_content, export_context, filename } = value
    const expiresAfter = nullableString(value.expires_after)
    const exception = nullableString(value.exception)
    if (
        typeof id !== 'number' ||
        typeof export_format !== 'string' ||
        typeof created_at !== 'string' ||
        typeof has_content !== 'boolean' ||
        expiresAfter === undefined ||
        exception === undefined
    ) {
        return null
    }
    return {
        id,
        export_format,
        created_at,
        has_content,
        export_context: isRecord(export_context) ? (export_context as ReplayVideoExportContext) : null,
        filename: typeof filename === 'string' ? filename : '',
        expires_after: expiresAfter,
        exception,
    }
}

function requireExport(value: unknown): ReplayVideoExport {
    const parsed = parseExport(value)
    if (!parsed) {
        throw new Error('Unexpected export response')
    }
    return parsed
}

/**
 * `GET exports/`, newest first, first page only. The server lists the current user's exports alone. The session and
 * format are checked here too, because a server that ignores the filters returns every export of the user.
 */
export async function listReplayVideoExports(sessionId: string, signal?: AbortSignal): Promise<ReplayVideoExport[]> {
    const page = await apiJson<{ results?: unknown[] }>(projectPath('exports/'), {
        query: { session_recording_id: sessionId, export_format: REPLAY_VIDEO_FORMAT },
        signal,
    })
    return (Array.isArray(page?.results) ? page.results : [])
        .map(parseExport)
        .filter(
            (asset): asset is ReplayVideoExport =>
                asset !== null &&
                asset.export_format === REPLAY_VIDEO_FORMAT &&
                asset.export_context?.session_recording_id === sessionId
        )
}

/**
 * `POST exports/` with the web player's whole-recording video body. Each call counts against the team's monthly
 * video export cap, so reuse an export from `pickReusableExport` first.
 */
export async function createReplayVideoExport(
    sessionId: string,
    durationSeconds: number,
    signal?: AbortSignal
): Promise<ReplayVideoExport> {
    if (durationSeconds > MAX_REPLAY_VIDEO_SECONDS) {
        throw new ReplayVideoError('too_long')
    }
    const created = await apiJson<unknown>(projectPath('exports/'), {
        method: 'POST',
        json: {
            export_format: REPLAY_VIDEO_FORMAT,
            export_context: {
                session_recording_id: sessionId,
                timestamp: 0,
                width: 1400,
                height: 600,
                filename: `replay-${sessionId}`,
                duration: Math.max(0, Math.floor(durationSeconds)),
                // The server's default too, sent so that every server version skips idle time.
                skip_inactivity: true,
            },
        },
        signal,
    })
    return requireExport(created)
}

export async function getReplayVideoExport(id: number, signal?: AbortSignal): Promise<ReplayVideoExport> {
    return requireExport(await apiJson<unknown>(projectPath(`exports/${id}/`), { signal }))
}

function timeOf(iso: string | null): number {
    return iso === null ? Number.NaN : Date.parse(iso)
}

/** Epoch ms of the export's creation. An unreadable time sorts as the oldest. */
function createdAt(asset: ReplayVideoExport): number {
    const time = timeOf(asset.created_at)
    return Number.isNaN(time) ? 0 : time
}

/**
 * The export to play instead of rendering again: the newest finished one that has not expired, else the newest one
 * still rendering within the render timeout, else null. Server timestamps compare with the server clock.
 */
export function pickReusableExport(
    exports: readonly ReplayVideoExport[],
    durationSeconds: number | null,
    now: number = serverNow()
): ReplayVideoExport | null {
    if (durationSeconds === null || !Number.isFinite(durationSeconds)) {
        return null
    }
    const newestFirst = exports
        .filter((asset) => {
            const context = asset.export_context
            return (
                context?.timestamp === 0 &&
                typeof context.duration === 'number' &&
                Number.isFinite(context.duration) &&
                context.duration >= Math.max(0, Math.floor(durationSeconds))
            )
        })
        .sort((a, b) => createdAt(b) - createdAt(a))
    const ready = newestFirst.find(
        (asset) =>
            asset.has_content && !asset.exception && (asset.expires_after === null || timeOf(asset.expires_after) > now)
    )
    if (ready) {
        return ready
    }
    return (
        newestFirst.find(
            (asset) => !asset.has_content && !asset.exception && now - createdAt(asset) < REPLAY_VIDEO_RENDER_TIMEOUT_MS
        ) ?? null
    )
}

function hostOf(url: string): string | null {
    try {
        return new URL(url).host
    } catch {
        return null
    }
}

/** Stops the download of a video the player fetches again on its own. */
function discardBody(response: Response): void {
    try {
        response.body?.cancel().catch(() => undefined)
    } catch {
        // A runtime without a body stream has already read the whole response.
    }
}

async function errorBody(response: Response): Promise<unknown> {
    try {
        const text = await transport(() => response.text())
        return text ? (JSON.parse(text) as unknown) : undefined
    } catch {
        return undefined
    }
}

/**
 * Where the player loads a finished video. `GET exports/{id}/content/` redirects to a signed object-storage URL that
 * works for an hour without credentials. The request asks not to follow it, so the bearer token never goes to the
 * storage host. A runtime that follows it anyway lands on the storage host: its URL is still signed, so the player
 * gets it even when that hop failed. Local dev serves the bytes from the API itself, which needs the bearer header.
 */
export async function resolveReplayVideoSource(id: number, signal?: AbortSignal): Promise<ReplayVideoSource> {
    const path = projectPath(`exports/${id}/content/`)
    const requested = apiUrl(path)
    const expiresAt = Date.now() + 60 * 60_000
    return apiReadResponse(path, { redirect: 'manual', signal }, async (response) => {
        const location = response.headers.get('Location')
        if (response.status >= 300 && response.status < 400 && location) {
            return { uri: location, expiresAt }
        }
        const landed = typeof response.url === 'string' && response.url ? response.url : requested
        if (/^https?:\/\//i.test(landed) && hostOf(landed) !== hostOf(requested)) {
            discardBody(response)
            return { uri: landed, expiresAt }
        }
        if (response.ok) {
            discardBody(response)
            return { uri: requested, headers: authorizationHeaders() }
        }
        throw new ApiError(response.status, await errorBody(response), response.headers)
    })
}
