import {
    tasksRunsArtifactsFinalizeUploadCreate,
    tasksRunsArtifactsPrepareUploadCreate,
    tasksStagedArtifactsFinalizeUploadCreate,
    tasksStagedArtifactsPrepareUploadCreate,
} from 'products/tasks/frontend/generated/api'

import { uploadRunAttachments, uploadStagedTaskAttachments } from './artifactUpload'

jest.mock('products/tasks/frontend/generated/api', () => ({
    tasksRunsArtifactsFinalizeUploadCreate: jest.fn(),
    tasksRunsArtifactsPrepareUploadCreate: jest.fn(),
    tasksStagedArtifactsFinalizeUploadCreate: jest.fn(),
    tasksStagedArtifactsPrepareUploadCreate: jest.fn(),
}))

const prepareRun = tasksRunsArtifactsPrepareUploadCreate as jest.Mock
const finalizeRun = tasksRunsArtifactsFinalizeUploadCreate as jest.Mock
const prepareStaged = tasksStagedArtifactsPrepareUploadCreate as jest.Mock
const finalizeStaged = tasksStagedArtifactsFinalizeUploadCreate as jest.Mock

function preparedArtifact(id: string, name: string, contentType: string): Record<string, unknown> {
    return {
        id,
        name,
        type: 'user_attachment',
        source: 'posthog_ai',
        size: 3,
        content_type: contentType,
        storage_path: `artifacts/${id}/${name}`,
        expires_in: 900,
        presigned_post: { url: 'https://s3.test/upload', fields: { key: `artifacts/${id}/${name}`, policy: 'p' } },
    }
}

describe('artifact uploads', () => {
    let fetchMock: jest.Mock

    beforeEach(() => {
        jest.clearAllMocks()
        fetchMock = jest.fn().mockResolvedValue({ ok: true })
        global.fetch = fetchMock as unknown as typeof fetch
    })

    it('does nothing at all when there is nothing to upload', async () => {
        await expect(uploadRunAttachments('1', 'task', 'run', [])).resolves.toEqual([])
        expect(prepareRun).not.toHaveBeenCalled()
        expect(fetchMock).not.toHaveBeenCalled()
    })

    it('prepares, uploads and finalizes a run attachment, answering with its id', async () => {
        prepareRun.mockResolvedValue({ artifacts: [preparedArtifact('art-1', 'notes.md', 'text/markdown')] })
        finalizeRun.mockResolvedValue({ artifacts: [] })

        const ids = await uploadRunAttachments('1', 'task', 'run', [new File(['abc'], 'notes.md')])

        expect(ids).toEqual(['art-1'])
        expect(prepareRun).toHaveBeenCalledWith('1', 'task', 'run', {
            artifacts: [
                {
                    name: 'notes.md',
                    type: 'user_attachment',
                    source: 'posthog_ai',
                    size: 3,
                    content_type: 'text/markdown',
                },
            ],
        })
        expect(finalizeRun).toHaveBeenCalledWith('1', 'task', 'run', {
            artifacts: [
                {
                    id: 'art-1',
                    name: 'notes.md',
                    type: 'user_attachment',
                    source: 'posthog_ai',
                    storage_path: 'artifacts/art-1/notes.md',
                    content_type: 'text/markdown',
                },
            ],
        })
    })

    it('posts the presigned form fields verbatim, ahead of the file', async () => {
        prepareStaged.mockResolvedValue({ artifacts: [preparedArtifact('art-2', 'shot.png', 'image/png')] })
        finalizeStaged.mockResolvedValue({ artifacts: [] })

        await uploadStagedTaskAttachments('1', 'task', [new File(['abc'], 'shot.png')])

        expect(prepareStaged).toHaveBeenCalledWith('1', 'task', expect.anything())
        const [url, request] = fetchMock.mock.calls[0]
        expect(url).toBe('https://s3.test/upload')
        expect(request.method).toBe('POST')
        const body = request.body as FormData
        expect([...body.keys()]).toEqual(['key', 'policy', 'file'])
        expect(body.get('key')).toBe('artifacts/art-2/shot.png')
    })

    it('rejects the batch when one upload fails, and never finalizes', async () => {
        prepareRun.mockResolvedValue({
            artifacts: [
                preparedArtifact('art-1', 'a.md', 'text/markdown'),
                preparedArtifact('art-2', 'b.md', 'text/markdown'),
            ],
        })
        fetchMock.mockResolvedValueOnce({ ok: true }).mockResolvedValueOnce({ ok: false })

        await expect(
            uploadRunAttachments('1', 'task', 'run', [new File(['a'], 'a.md'), new File(['b'], 'b.md')])
        ).rejects.toThrow("Couldn't upload b.md")
        expect(finalizeRun).not.toHaveBeenCalled()
    })

    it('rejects when the server prepares a different number of uploads than were asked for', async () => {
        prepareRun.mockResolvedValue({ artifacts: [preparedArtifact('art-1', 'a.md', 'text/markdown')] })

        await expect(
            uploadRunAttachments('1', 'task', 'run', [new File(['a'], 'a.md'), new File(['b'], 'b.md')])
        ).rejects.toThrow("Couldn't prepare every attachment for upload")
        expect(fetchMock).not.toHaveBeenCalled()
    })
})
