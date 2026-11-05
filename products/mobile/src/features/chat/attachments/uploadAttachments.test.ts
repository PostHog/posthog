import { setAuthProvider } from '@/api/client'

import type { PendingAttachment } from './types'
import { AttachmentUploadError, uploadAttachments } from './uploadAttachments'

const S3_URL = 'https://uploads.example.com/bucket'

jest.mock('expo-file-system', () => ({
    File: class {
        readonly uri: string

        constructor(uri: string) {
            this.uri = uri
        }

        async bytes(): Promise<Uint8Array> {
            return new TextEncoder().encode(`contents of ${this.uri}`)
        }
    },
}))

/** Node's `FormData` takes only a real `Blob` as a file part, so the test records the parts instead. */
class RecordingFormData {
    readonly parts: [string, unknown][] = []

    append(key: string, value: unknown): void {
        this.parts.push([key, value])
    }
}

function attachment(name: string, contentType: string): PendingAttachment {
    return { id: name, uri: `file:///picked/${name}`, name, size: 100, contentType, isImage: false }
}

interface Call {
    url: string
    init: { method?: string; body?: unknown; headers?: Record<string, string>; signal?: AbortSignal }
}

function s3Response(status: number): unknown {
    return { ok: status < 300, status, headers: { get: () => null }, text: async () => '' }
}

describe('uploadAttachments', () => {
    const originalFormData = globalThis.FormData
    let calls: Call[]
    let s3Reply: (index: number, signal: AbortSignal | undefined) => Promise<unknown>

    beforeEach(() => {
        calls = []
        s3Reply = async () => s3Response(204)
        globalThis.FormData = RecordingFormData as unknown as typeof FormData
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        let s3Count = 0
        globalThis.fetch = jest.fn(async (url: string, init: Call['init'] = {}) => {
            calls.push({ url, init })
            if (url === S3_URL) {
                return s3Reply(s3Count++, init.signal)
            }
            const body = url.includes('prepare_upload')
                ? {
                      artifacts: ['art-1', 'art-2'].map((id, index) => ({
                          id,
                          name: `server-${index}`,
                          storage_path: `staged/${id}`,
                          presigned_post: { url: S3_URL, fields: { key: `staged/${id}`, policy: `policy-${id}` } },
                      })),
                  }
                : { artifacts: [] }
            return { ok: true, status: 200, headers: { get: () => null }, text: async () => JSON.stringify(body) }
        }) as unknown as typeof fetch
    })

    afterEach(() => {
        globalThis.FormData = originalFormData
        setAuthProvider(null)
    })

    test('prepares, posts each file to S3 without the PostHog token, then finalizes, and returns ids in order', async () => {
        const ids = await uploadAttachments({ kind: 'staged', taskId: 'task-1' }, [
            attachment('notes.md', 'text/markdown'),
            attachment('shot.png', 'image/png'),
        ])

        expect(ids).toEqual(['art-1', 'art-2'])
        expect(calls.map((call) => call.url)).toEqual([
            'https://app.example.com/api/projects/2/tasks/task-1/staged_artifacts/prepare_upload/',
            S3_URL,
            S3_URL,
            'https://app.example.com/api/projects/2/tasks/task-1/staged_artifacts/finalize_upload/',
        ])
        const [first, second] = calls.slice(1, 3)
        expect(first?.init.headers).toBeUndefined()
        const parts = (first?.init.body as RecordingFormData).parts
        expect(parts).toEqual([
            ['key', 'staged/art-1'],
            ['policy', 'policy-art-1'],
            ['file', expect.objectContaining({ name: 'notes.md', type: 'text/markdown', bytes: expect.any(Function) })],
        ])
        const filePart = parts[2]?.[1] as { bytes: () => Promise<Uint8Array> }
        expect(new TextDecoder().decode(await filePart.bytes())).toBe('contents of file:///picked/notes.md')
        expect((second?.init.body as RecordingFormData).parts.at(-1)?.[0]).toBe('file')
        expect(JSON.parse(calls[3]?.init.body as string)).toEqual({
            artifacts: [
                {
                    id: 'art-1',
                    name: 'server-0',
                    type: 'user_attachment',
                    source: 'posthog_ai',
                    storage_path: 'staged/art-1',
                    content_type: 'text/markdown',
                },
                {
                    id: 'art-2',
                    name: 'server-1',
                    type: 'user_attachment',
                    source: 'posthog_ai',
                    storage_path: 'staged/art-2',
                    content_type: 'image/png',
                },
            ],
        })
    })

    test('one failed S3 post stops the other posts, rejects the batch and finalizes nothing', async () => {
        s3Reply = (index, signal) =>
            index === 1
                ? Promise.resolve(s3Response(403))
                : new Promise((_resolve, reject) => {
                      signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
                  })

        await expect(
            uploadAttachments({ kind: 'run', taskId: 'task-1', runId: 'run-1' }, [
                attachment('a.txt', 'text/plain'),
                attachment('b.txt', 'text/plain'),
            ])
        ).rejects.toEqual(new AttachmentUploadError("Couldn't upload b.txt", 403))
        expect(calls[0]?.url).toBe(
            'https://app.example.com/api/projects/2/tasks/task-1/runs/run-1/artifacts/prepare_upload/'
        )
        expect(calls[1]?.init.signal?.aborted).toBe(true)
        expect(calls.some((call) => call.url.includes('finalize_upload'))).toBe(false)
    })
})
