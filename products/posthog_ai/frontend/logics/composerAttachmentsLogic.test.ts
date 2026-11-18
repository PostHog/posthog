import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import { MAX_ATTACHMENTS_PER_MESSAGE } from '../utils/attachments'
import { composerAttachmentsLogic } from './composerAttachmentsLogic'

function fileOfSize(name: string, size: number): File {
    const file = new File(['x'], name)
    Object.defineProperty(file, 'size', { value: size })
    return file
}

describe('composerAttachmentsLogic', () => {
    let logic: ReturnType<typeof composerAttachmentsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = composerAttachmentsLogic({ attachmentsKey: 'scene' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('stages the files it is given, in order', () => {
        logic.actions.addFiles([new File(['a'], 'a.md'), new File(['b'], 'b.png')])

        expect(logic.values.attachments.map((attachment) => attachment.file.name)).toEqual(['a.md', 'b.png'])
        expect(logic.values.attachedFiles.map((file) => file.name)).toEqual(['a.md', 'b.png'])
        expect(logic.values.hasAttachments).toBe(true)
    })

    it('adds to what is already staged rather than replacing it', () => {
        logic.actions.addFiles([new File(['a'], 'a.md')])
        logic.actions.addFiles([new File(['b'], 'b.md')])

        expect(logic.values.attachments).toHaveLength(2)
    })

    it('gives every chip its own id, even for two files of the same name', () => {
        logic.actions.addFiles([new File(['a'], 'same.md'), new File(['b'], 'same.md')])

        const [first, second] = logic.values.attachments
        expect(first.id).not.toBe(second.id)
    })

    it('removes one chip and leaves the rest', () => {
        logic.actions.addFiles([new File(['a'], 'a.md'), new File(['b'], 'b.md')])
        logic.actions.removeAttachment(logic.values.attachments[0].id)

        expect(logic.values.attachments.map((attachment) => attachment.file.name)).toEqual(['b.md'])
    })

    it('drops an oversized file and says why, keeping the rest of the batch', () => {
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation()

        logic.actions.addFiles([fileOfSize('huge.png', 40 * 1024 * 1024), new File(['ok'], 'ok.md')])

        expect(logic.values.attachments.map((attachment) => attachment.file.name)).toEqual(['ok.md'])
        expect(toast).toHaveBeenCalledWith('huge.png is over the 30MB limit')
    })

    it('stops at the per-message limit', () => {
        logic.actions.addFiles(
            Array.from({ length: MAX_ATTACHMENTS_PER_MESSAGE + 3 }, (_, index) => new File(['x'], `file-${index}.md`))
        )

        expect(logic.values.attachments).toHaveLength(MAX_ATTACHMENTS_PER_MESSAGE)
        expect(logic.values.isAtAttachmentLimit).toBe(true)
    })

    it('removes only the files a send took, leaving one added since', () => {
        logic.actions.addFiles([new File(['a'], 'a.md'), new File(['b'], 'b.md')])
        const sent = logic.values.attachments.map((attachment) => attachment.id)
        logic.actions.addFiles([new File(['c'], 'c.md')])

        logic.actions.removeAttachments(sent)

        expect(logic.values.attachments.map((attachment) => attachment.file.name)).toEqual(['c.md'])
    })

    describe('files promised to the queue', () => {
        beforeEach(() => {
            logic.actions.addFiles([new File(['a'], 'queued.md')])
            logic.actions.claimAttachmentsForQueue()
        })

        it('leaves the composer, so a draft send cannot take them', () => {
            expect(logic.values.stagedAttachments).toEqual([])
            expect(logic.values.queuedAttachments.map((attachment) => attachment.file.name)).toEqual(['queued.md'])
            expect(logic.values.hasAttachments).toBe(false)
        })

        it('still counts against the per-message limit', () => {
            logic.actions.addFiles(Array.from({ length: 10 }, (_, index) => new File(['x'], `f-${index}.md`)))

            expect(logic.values.attachments).toHaveLength(MAX_ATTACHMENTS_PER_MESSAGE)
        })

        it('comes back to the composer when the queue is released', () => {
            logic.actions.releaseQueuedAttachments()

            expect(logic.values.stagedAttachments.map((attachment) => attachment.file.name)).toEqual(['queued.md'])
            expect(logic.values.queuedAttachments).toEqual([])
        })
    })

    it('keys the staged files per composer, so one composer never sees another one’s', () => {
        const other = composerAttachmentsLogic({ attachmentsKey: 'side-panel' })
        other.mount()

        logic.actions.addFiles([new File(['a'], 'a.md')])

        expect(other.values.attachments).toEqual([])
        other.unmount()
    })
})
