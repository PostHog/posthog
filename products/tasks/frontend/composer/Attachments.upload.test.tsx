import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
    tasksRunsArtifactsFinalizeUploadCreate,
    tasksRunsArtifactsPrepareUploadCreate,
    tasksRunsCommandCreate,
} from '../generated/api'
import { TaskRunArtifactTypeEnumApi } from '../generated/api.schemas'
import {
    CLOUD_ATTACHMENT_MAX_SIZE_BYTES,
    CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES,
    sendRunCommand,
    uploadRunAttachments,
} from './api'
import { AttachmentButton, AttachmentsBar } from './Attachments'

jest.mock('../generated/api', () => ({
    tasksRunsArtifactsPrepareUploadCreate: jest.fn(),
    tasksRunsArtifactsFinalizeUploadCreate: jest.fn(),
    tasksRunsCommandCreate: jest.fn(),
}))

const mockedPrepare = tasksRunsArtifactsPrepareUploadCreate as jest.Mock
const mockedFinalize = tasksRunsArtifactsFinalizeUploadCreate as jest.Mock
const mockedCommand = tasksRunsCommandCreate as jest.Mock

function makeFile(name: string, type: string, size: number): File {
    const file = new File(['x'], name, { type })
    Object.defineProperty(file, 'size', { value: size })
    return file
}

function preparedArtifact(
    id: string,
    name: string,
    contentType: string,
    overrides: Record<string, unknown> = {}
): Record<string, unknown> {
    return {
        id,
        name,
        type: TaskRunArtifactTypeEnumApi.UserAttachment,
        source: 'posthog_web',
        size: 1,
        content_type: contentType,
        storage_path: `runs/r1/${id}`,
        expires_in: 3600,
        presigned_post: { url: 'https://s3.example/upload', fields: { key: `runs/r1/${id}`, policy: 'p' } },
        ...overrides,
    }
}

describe('Attachments and upload api', () => {
    let fetchMock: jest.Mock

    beforeEach(() => {
        jest.clearAllMocks()
        fetchMock = jest.fn().mockResolvedValue({ ok: true })
        global.fetch = fetchMock as unknown as typeof fetch
    })

    afterEach(() => {
        cleanup()
    })

    describe('size limit constants', () => {
        it('caps generic attachments at 30MB and PDFs at 10MB', () => {
            expect(CLOUD_ATTACHMENT_MAX_SIZE_BYTES).toBe(30 * 1024 * 1024)
            expect(CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES).toBe(10 * 1024 * 1024)
        })
    })

    describe('uploadRunAttachments', () => {
        it('returns [] without calling the api when there are no files', async () => {
            const ids = await uploadRunAttachments('p1', 't1', 'r1', [])
            expect(ids).toEqual([])
            expect(mockedPrepare).not.toHaveBeenCalled()
            expect(fetchMock).not.toHaveBeenCalled()
            expect(mockedFinalize).not.toHaveBeenCalled()
        })

        it('runs prepare -> presigned POST -> finalize and returns artifact ids', async () => {
            const file = makeFile('notes.txt', 'text/plain', 5)
            mockedPrepare.mockResolvedValue({ artifacts: [preparedArtifact('a1', 'notes.txt', 'text/plain')] })
            mockedFinalize.mockResolvedValue({ artifacts: [{ id: 'a1' }] })

            const ids = await uploadRunAttachments('p1', 't1', 'r1', [file])

            expect(ids).toEqual(['a1'])
            expect(mockedPrepare).toHaveBeenCalledWith('p1', 't1', 'r1', {
                artifacts: [
                    {
                        name: 'notes.txt',
                        type: TaskRunArtifactTypeEnumApi.UserAttachment,
                        source: 'posthog_web',
                        size: 5,
                        content_type: 'text/plain',
                    },
                ],
            })
            expect(fetchMock).toHaveBeenCalledTimes(1)
            expect(fetchMock).toHaveBeenCalledWith(
                'https://s3.example/upload',
                expect.objectContaining({ method: 'POST' })
            )
            expect(mockedFinalize).toHaveBeenCalledTimes(1)
        })

        it('posts presigned fields verbatim along with the file in the form body', async () => {
            const file = makeFile('img.png', 'image/png', 10)
            mockedPrepare.mockResolvedValue({
                artifacts: [
                    preparedArtifact('a1', 'img.png', 'image/png', {
                        presigned_post: { url: 'https://s3.example/u', fields: { key: 'runs/r1/a1', acl: 'private' } },
                    }),
                ],
            })
            mockedFinalize.mockResolvedValue({ artifacts: [{ id: 'a1' }] })

            await uploadRunAttachments('p1', 't1', 'r1', [file])

            const body = fetchMock.mock.calls[0][1].body as FormData
            expect(body).toBeInstanceOf(FormData)
            expect(body.get('key')).toBe('runs/r1/a1')
            expect(body.get('acl')).toBe('private')
            expect(body.get('file')).toBeInstanceOf(File)
        })

        it('uploads multiple files in parallel and preserves index-to-file mapping', async () => {
            const a = makeFile('a.txt', 'text/plain', 1)
            const b = makeFile('b.txt', 'text/plain', 2)
            mockedPrepare.mockResolvedValue({
                artifacts: [
                    preparedArtifact('a1', 'a.txt', 'text/plain'),
                    preparedArtifact('a2', 'b.txt', 'text/plain'),
                ],
            })
            mockedFinalize.mockResolvedValue({ artifacts: [{ id: 'a1' }, { id: 'a2' }] })

            const ids = await uploadRunAttachments('p1', 't1', 'r1', [a, b])

            expect(ids).toEqual(['a1', 'a2'])
            expect(fetchMock).toHaveBeenCalledTimes(2)
            const firstBody = fetchMock.mock.calls[0][1].body as FormData
            const secondBody = fetchMock.mock.calls[1][1].body as FormData
            expect((firstBody.get('file') as File).name).toBe('a.txt')
            expect((secondBody.get('file') as File).name).toBe('b.txt')
        })

        it('infers content type from extension when the browser provides none', async () => {
            const file = makeFile('data.json', '', 5)
            mockedPrepare.mockResolvedValue({ artifacts: [preparedArtifact('a1', 'data.json', 'application/json')] })
            mockedFinalize.mockResolvedValue({ artifacts: [{ id: 'a1' }] })

            await uploadRunAttachments('p1', 't1', 'r1', [file])

            expect(mockedPrepare.mock.calls[0][3].artifacts[0].content_type).toBe('application/json')
        })

        it('falls back to application/octet-stream for unknown extensionless files', async () => {
            const file = makeFile('mystery', '', 5)
            mockedPrepare.mockResolvedValue({
                artifacts: [preparedArtifact('a1', 'mystery', 'application/octet-stream')],
            })
            mockedFinalize.mockResolvedValue({ artifacts: [{ id: 'a1' }] })

            await uploadRunAttachments('p1', 't1', 'r1', [file])

            expect(mockedPrepare.mock.calls[0][3].artifacts[0].content_type).toBe('application/octet-stream')
        })

        it('rejects a generic file larger than the 30MB limit before preparing', async () => {
            const file = makeFile('big.txt', 'text/plain', CLOUD_ATTACHMENT_MAX_SIZE_BYTES + 1)

            await expect(uploadRunAttachments('p1', 't1', 'r1', [file])).rejects.toThrow(
                'big.txt exceeds the 30MB attachment limit'
            )
            expect(mockedPrepare).not.toHaveBeenCalled()
        })

        it('allows a generic file exactly at the 30MB limit', async () => {
            const file = makeFile('edge.txt', 'text/plain', CLOUD_ATTACHMENT_MAX_SIZE_BYTES)
            mockedPrepare.mockResolvedValue({ artifacts: [preparedArtifact('a1', 'edge.txt', 'text/plain')] })
            mockedFinalize.mockResolvedValue({ artifacts: [{ id: 'a1' }] })

            await expect(uploadRunAttachments('p1', 't1', 'r1', [file])).resolves.toEqual(['a1'])
        })

        it('holds PDFs to the tighter 10MB limit by extension', async () => {
            const file = makeFile('doc.pdf', '', CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES + 1)

            await expect(uploadRunAttachments('p1', 't1', 'r1', [file])).rejects.toThrow(
                'doc.pdf exceeds the 10MB attachment limit'
            )
            expect(mockedPrepare).not.toHaveBeenCalled()
        })

        it('holds PDFs to the 10MB limit by content type even without a .pdf extension', async () => {
            const file = makeFile('doc', 'application/pdf', CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES + 1)

            await expect(uploadRunAttachments('p1', 't1', 'r1', [file])).rejects.toThrow(
                'doc exceeds the 10MB attachment limit'
            )
        })

        it('lets a PDF between 10MB and 30MB through only because it is not a PDF type', async () => {
            const file = makeFile('doc.pdf', '', CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES)
            mockedPrepare.mockResolvedValue({ artifacts: [preparedArtifact('a1', 'doc.pdf', 'application/pdf')] })
            mockedFinalize.mockResolvedValue({ artifacts: [{ id: 'a1' }] })

            await expect(uploadRunAttachments('p1', 't1', 'r1', [file])).resolves.toEqual(['a1'])
        })

        it('throws and does not finalize when the presigned upload fails', async () => {
            const file = makeFile('notes.txt', 'text/plain', 5)
            mockedPrepare.mockResolvedValue({ artifacts: [preparedArtifact('a1', 'notes.txt', 'text/plain')] })
            fetchMock.mockResolvedValue({ ok: false })

            await expect(uploadRunAttachments('p1', 't1', 'r1', [file])).rejects.toThrow('Failed to upload notes.txt')
            expect(mockedFinalize).not.toHaveBeenCalled()
        })

        it('filters out finalized artifacts that lack a string id', async () => {
            const file = makeFile('notes.txt', 'text/plain', 5)
            mockedPrepare.mockResolvedValue({ artifacts: [preparedArtifact('a1', 'notes.txt', 'text/plain')] })
            mockedFinalize.mockResolvedValue({ artifacts: [{ id: 'a1' }, { id: undefined }, { id: null }] })

            const ids = await uploadRunAttachments('p1', 't1', 'r1', [file])
            expect(ids).toEqual(['a1'])
        })
    })

    describe('sendRunCommand', () => {
        it('wraps the method in a 2.0 envelope and returns the result', async () => {
            mockedCommand.mockResolvedValue({ result: { ok: true } })

            const result = await sendRunCommand('p1', 't1', 'r1', 'cancel' as never)

            expect(result).toEqual({ ok: true })
            expect(mockedCommand).toHaveBeenCalledWith('p1', 't1', 'r1', { jsonrpc: '2.0', method: 'cancel' })
        })

        it('includes params when provided', async () => {
            mockedCommand.mockResolvedValue({ result: undefined })

            await sendRunCommand('p1', 't1', 'r1', 'user_message' as never, { artifact_ids: ['a1'] } as never)

            expect(mockedCommand).toHaveBeenCalledWith('p1', 't1', 'r1', {
                jsonrpc: '2.0',
                method: 'user_message',
                params: { artifact_ids: ['a1'] },
            })
        })

        it('throws with the error message when the response carries an error', async () => {
            mockedCommand.mockResolvedValue({ error: { message: 'boom' } })

            await expect(sendRunCommand('p1', 't1', 'r1', 'cancel' as never)).rejects.toThrow('boom')
        })

        it('throws a generic message when the error has no message', async () => {
            mockedCommand.mockResolvedValue({ error: {} })

            await expect(sendRunCommand('p1', 't1', 'r1', 'cancel' as never)).rejects.toThrow('Command failed')
        })
    })

    describe('AttachmentsBar', () => {
        it('renders nothing when there are no files', () => {
            const { container } = render(<AttachmentsBar files={[]} onRemove={jest.fn()} />)
            expect(container).toBeEmptyDOMElement()
        })

        it('renders the file name for each attachment', () => {
            const files = [makeFile('a.txt', 'text/plain', 1), makeFile('b.pdf', 'application/pdf', 1)]
            render(<AttachmentsBar files={files} onRemove={jest.fn()} />)

            expect(screen.getByText('a.txt')).toBeInTheDocument()
            expect(screen.getByText('b.pdf')).toBeInTheDocument()
        })

        it('renders an image thumbnail for image files via an object URL', () => {
            const createObjectURL = jest.fn().mockReturnValue('blob:fake')
            const original = URL.createObjectURL
            URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL

            render(<AttachmentsBar files={[makeFile('pic.png', 'image/png', 1)]} onRemove={jest.fn()} />)

            const img = screen.getByAltText('pic.png') as HTMLImageElement
            expect(img.tagName).toBe('IMG')
            expect(img.src).toBe('blob:fake')
            expect(createObjectURL).toHaveBeenCalled()

            URL.createObjectURL = original
        })

        it('does not render an img for non-image files', () => {
            render(<AttachmentsBar files={[makeFile('a.txt', 'text/plain', 1)]} onRemove={jest.fn()} />)
            expect(screen.queryByAltText('a.txt')).not.toBeInTheDocument()
        })

        it('revokes the object URL on unmount to avoid leaking blobs', () => {
            const revokeObjectURL = jest.fn()
            const originalCreate = URL.createObjectURL
            const originalRevoke = URL.revokeObjectURL
            URL.createObjectURL = (() => 'blob:fake') as unknown as typeof URL.createObjectURL
            URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL

            const { unmount } = render(
                <AttachmentsBar files={[makeFile('pic.png', 'image/png', 1)]} onRemove={jest.fn()} />
            )
            unmount()
            expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake')

            URL.createObjectURL = originalCreate
            URL.revokeObjectURL = originalRevoke
        })

        it('calls onRemove with the index of the removed attachment', async () => {
            const onRemove = jest.fn()
            const files = [makeFile('a.txt', 'text/plain', 1), makeFile('b.txt', 'text/plain', 1)]
            render(<AttachmentsBar files={files} onRemove={onRemove} />)

            await userEvent.click(screen.getByRole('button', { name: 'Remove b.txt' }))
            expect(onRemove).toHaveBeenCalledWith(1)
        })
    })

    describe('AttachmentButton', () => {
        it('passes selected files to onAddFiles', async () => {
            const onAddFiles = jest.fn()
            const { container } = render(<AttachmentButton onAddFiles={onAddFiles} />)
            const input = container.querySelector('input[type="file"]') as HTMLInputElement

            await userEvent.upload(input, [makeFile('a.txt', 'text/plain', 1), makeFile('pic.png', 'image/png', 1)])

            expect(onAddFiles).toHaveBeenCalledTimes(1)
            const passed = onAddFiles.mock.calls[0][0] as File[]
            expect(passed.map((f) => f.name)).toEqual(['a.txt', 'pic.png'])
        })

        it('accepts images and the documented text/code file extensions', () => {
            const { container } = render(<AttachmentButton onAddFiles={jest.fn()} />)
            const input = container.querySelector('input[type="file"]') as HTMLInputElement
            const accept = input.getAttribute('accept') ?? ''

            expect(accept).toContain('image/*')
            expect(accept).toContain('.pdf')
            expect(accept).toContain('.py')
        })

        it('disables the trigger button when disabled', () => {
            render(<AttachmentButton onAddFiles={jest.fn()} disabled />)
            // LemonButton uses aria-disabled rather than the native disabled attribute.
            expect(screen.getByRole('button', { name: 'Attach files' })).toHaveAttribute('aria-disabled', 'true')
        })

        it('does not invoke onAddFiles when the selection is empty', async () => {
            const onAddFiles = jest.fn()
            const { container } = render(<AttachmentButton onAddFiles={onAddFiles} />)
            const input = container.querySelector('input[type="file"]') as HTMLInputElement

            expect(input).toBeInTheDocument()
            expect(onAddFiles).not.toHaveBeenCalled()
        })
    })
})
