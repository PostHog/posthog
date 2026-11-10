import { ApiError, NotSignedInError, setAuthProvider } from './client'
import {
    createReplayVideoExport,
    pickReusableExport,
    type ReplayVideoErrorKind,
    type ReplayVideoExport,
    resolveReplayVideoSource,
    toReplayVideoError,
} from './replayVideo'
import { TransportError } from './transport'

const NOW = Date.parse('2026-11-05T12:00:00Z')
const MINUTE_MS = 60_000

function asset(id: number, minutesAgo: number, fields: Partial<ReplayVideoExport> = {}): ReplayVideoExport {
    return {
        id,
        export_format: 'video/mp4',
        created_at: new Date(NOW - minutesAgo * MINUTE_MS).toISOString(),
        has_content: false,
        export_context: { session_recording_id: 's-1', timestamp: 0, duration: 120 },
        filename: 'replay-s-1',
        expires_after: null,
        exception: null,
        ...fields,
    }
}

function contentResponse(status: number, url: string, location?: string): Response & { cancel: jest.Mock } {
    const cancel = jest.fn(async () => undefined)
    return {
        ok: status >= 200 && status < 300,
        status,
        url,
        headers: { get: (name: string) => (name === 'Location' ? (location ?? null) : null) },
        body: { cancel },
        text: async () => '',
        cancel,
    } as unknown as Response & { cancel: jest.Mock }
}

describe('replay video API', () => {
    beforeEach(() =>
        setAuthProvider({
            getAuth: () => ({ host: 'https://us.example.com', accessToken: 'token', projectId: 7, session: 1 }),
            refreshAccessToken: async () => null,
        })
    )
    afterEach(() => {
        setAuthProvider(null)
        jest.useRealTimers()
    })

    test.each<[string, ReplayVideoExport[], number | null]>([
        ['the newest finished video', [asset(1, 30, { has_content: true }), asset(2, 5, { has_content: true })], 2],
        ['a finished video over a newer render', [asset(1, 30, { has_content: true }), asset(2, 5)], 1],
        [
            'a render once the finished video expired',
            [asset(1, 30, { has_content: true, expires_after: new Date(NOW - MINUTE_MS).toISOString() }), asset(2, 5)],
            2,
        ],
        [
            'a finished video that expires later',
            [asset(1, 30, { has_content: true, expires_after: new Date(NOW + MINUTE_MS).toISOString() })],
            1,
        ],
        ['the newer of two renders', [asset(1, 20), asset(2, 10)], 2],
        ['nothing for a render past the workflow timeout', [asset(1, 76)], null],
        ['nothing for a failed render', [asset(1, 5, { exception: 'Export failed' })], null],
    ])('reuse picks %s', (_name, exports, expectedId) => {
        expect(pickReusableExport(exports, 120.9, NOW)?.id ?? null).toBe(expectedId)
    })

    test.each([true, false])('ignores clips and unknown ranges when has_content is %s', (has_content) => {
        const full = asset(1, 30, { has_content })
        const clips = [
            { timestamp: 45, duration: 120 },
            { timestamp: 0, duration: 119 },
            { timestamp: 0 },
            { duration: 120 },
            { timestamp: 0, duration: Number.NaN },
        ].map((context, index) => asset(index + 2, 5, { has_content, export_context: context }))
        expect(pickReusableExport(clips, 120, NOW)).toBeNull()
        expect(pickReusableExport([...clips, full], 120, NOW)).toBe(full)
        expect(pickReusableExport([full], null, NOW)).toBeNull()
    })

    test('a recording longer than 3 hours never asks for a render', async () => {
        globalThis.fetch = jest.fn()
        await expect(createReplayVideoExport('s-1', 3 * 60 * 60 + 1)).rejects.toMatchObject({ kind: 'too_long' })
        expect(fetch).not.toHaveBeenCalled()
    })

    test.each([
        ['a redirect the request did not follow', contentResponse(302, '', 'https://storage.example.com/v.mp4?sig=1')],
        ['a followed redirect', contentResponse(200, 'https://storage.example.com/v.mp4?sig=1')],
        [
            'a followed redirect that the storage host refused',
            contentResponse(400, 'https://storage.example.com/v.mp4?sig=1'),
        ],
    ])('the video loads from the signed URL without the bearer token after %s', async (_name, response) => {
        jest.useFakeTimers({ now: NOW })
        globalThis.fetch = jest.fn().mockResolvedValue(response)
        await expect(resolveReplayVideoSource(42)).resolves.toEqual({
            uri: 'https://storage.example.com/v.mp4?sig=1',
            expiresAt: NOW + 60 * MINUTE_MS,
        })
        expect(fetch).toHaveBeenCalledWith(
            'https://us.example.com/api/projects/7/exports/42/content/',
            expect.objectContaining({ redirect: 'manual' })
        )
        if (response.status !== 302) {
            expect(response.cancel).toHaveBeenCalled()
        }
    })

    test('a video the API serves itself loads from the API with the bearer token', async () => {
        const url = 'https://us.example.com/api/projects/7/exports/42/content/'
        const response = contentResponse(200, url)
        globalThis.fetch = jest.fn().mockResolvedValue(response)
        await expect(resolveReplayVideoSource(42)).resolves.toEqual({
            uri: url,
            headers: { Authorization: 'Bearer token' },
        })
        expect(response.cancel).toHaveBeenCalled()
    })

    test.each<[string, unknown, ReplayVideoErrorKind, string]>([
        [
            'the monthly cap',
            new ApiError(400, {
                export_limit_exceeded: ['Your team has reached the limit of 10 full video exports this month.'],
            }),
            'limit_reached',
            'Your team has reached the limit of 10 full video exports this month.',
        ],
        [
            'the monthly cap without a reason',
            new ApiError(400, { export_limit_exceeded: [] }),
            'limit_reached',
            'Your team has reached its monthly limit for video exports.',
        ],
        [
            'a missing video',
            new ApiError(404, { detail: 'Not found.' }),
            'expired',
            'This video has expired. Prepare it again.',
        ],
        ['a rate limit', new ApiError(429, {}), 'network', 'Too many requests. Try again in a minute.'],
        [
            'a token without the export scope',
            new ApiError(403, { detail: "API key missing required scope 'export:write'" }),
            'missing_scope',
            "Video playback needs a permission this app doesn't have yet. Ask an admin to update the app's registration, then sign in again.",
        ],
        ['a sign-out', new NotSignedInError(), 'signed_out', 'Sign in to continue.'],
        ['no connection', new TransportError(), 'network', new TransportError().message],
        [
            'another bad request',
            new ApiError(400, { export_context: ['Invalid session_recording_id.'] }),
            'unknown',
            "Couldn't prepare this video. Try again.",
        ],
    ])('%s reads as its own kind', (_name, error, kind, message) => {
        expect(toReplayVideoError(error)).toMatchObject({ kind, message })
    })
})
