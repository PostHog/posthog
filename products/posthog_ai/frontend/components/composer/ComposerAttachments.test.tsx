import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { createRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { composerAttachmentsLogic } from '../../logics/composerAttachmentsLogic'
import { ComposerAttachments, useComposerAttachmentPaste } from './ComposerAttachments'

function PasteTarget(): JSX.Element {
    const onPaste = useComposerAttachmentPaste('scene')
    return <textarea onPaste={onPaste} />
}

function pasteInto(target: HTMLElement, files: File[], text: string): boolean {
    return fireEvent.paste(target, { clipboardData: { files, getData: () => text } })
}

function dropFiles(target: HTMLElement, files: File[]): boolean {
    return fireEvent.drop(target, { dataTransfer: { files, types: ['Files'] } })
}

describe('ComposerAttachments', () => {
    let logic: ReturnType<typeof composerAttachmentsLogic.build>
    const dropTargetRef = createRef<HTMLDivElement>()

    function renderWithDropTarget(): void {
        render(
            <div ref={dropTargetRef}>
                <ComposerAttachments attachmentsKey="scene" dropTargetRef={dropTargetRef} />
            </div>
        )
    }

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PHAI_TASKS_ATTACHEMENTS], {
            [FEATURE_FLAGS.PHAI_TASKS_ATTACHEMENTS]: true,
        })
        logic = composerAttachmentsLogic({ attachmentsKey: 'scene' })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('stages a dropped file once', () => {
        renderWithDropTarget()

        dropFiles(dropTargetRef.current!, [new File(['a'], 'shot.png')])

        expect(logic.values.attachments.map((attachment) => attachment.file.name)).toEqual(['shot.png'])
    })

    it('does not re-stage earlier files on a second drop', () => {
        renderWithDropTarget()

        dropFiles(dropTargetRef.current!, [new File(['a'], 'a.png'), new File(['b'], 'b.png')])
        dropFiles(dropTargetRef.current!, [new File(['c'], 'c.png'), new File(['d'], 'd.png')])

        expect(logic.values.attachments.map((attachment) => attachment.file.name)).toEqual([
            'a.png',
            'b.png',
            'c.png',
            'd.png',
        ])
    })

    it('ignores a drop that carries no files, so dragging text does not attach anything', () => {
        renderWithDropTarget()

        fireEvent.drop(dropTargetRef.current!, { dataTransfer: { files: [], types: ['text/plain'] } })

        expect(logic.values.attachments).toEqual([])
    })

    it('refuses a drop once the per-message limit is reached', () => {
        renderWithDropTarget()
        logic.actions.addFiles(Array.from({ length: 10 }, (_, index) => new File(['x'], `f-${index}.png`)))

        dropFiles(dropTargetRef.current!, [new File(['a'], 'over.png')])

        expect(logic.values.attachments).toHaveLength(10)
        expect(logic.values.attachments.map((attachment) => attachment.file.name)).not.toContain('over.png')
    })

    it('stages files chosen through the picker', () => {
        renderWithDropTarget()
        const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement

        fireEvent.change(fileInput, { target: { files: [new File(['a'], 'picked.png')] } })

        expect(logic.values.attachments.map((attachment) => attachment.file.name)).toEqual(['picked.png'])
    })

    describe('paste', () => {
        it('attaches a pasted file', () => {
            render(<PasteTarget />)

            pasteInto(document.querySelector('textarea')!, [new File(['a'], 'shot.png')], '')

            expect(logic.values.attachments.map((attachment) => attachment.file.name)).toEqual(['shot.png'])
        })

        it('lets the text through when the clipboard carries both', () => {
            render(<PasteTarget />)

            const notPrevented = pasteInto(
                document.querySelector('textarea')!,
                [new File(['a'], 'image.png')],
                'Revenue\t1200'
            )

            expect(notPrevented).toBe(true)
            expect(logic.values.attachments.map((attachment) => attachment.file.name)).toEqual(['image.png'])
        })

        it('takes the paste when there is no text to lose', () => {
            render(<PasteTarget />)

            const notPrevented = pasteInto(document.querySelector('textarea')!, [new File(['a'], 'image.png')], '')

            expect(notPrevented).toBe(false)
        })
    })

    it('stages nothing through any route while the feature flag is off', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        render(
            <div ref={dropTargetRef}>
                <ComposerAttachments attachmentsKey="scene" dropTargetRef={dropTargetRef} />
                <PasteTarget />
            </div>
        )

        expect(document.querySelector('[data-attr="posthog-ai-attach-file"]')).toBeNull()
        const notPrevented = dropFiles(dropTargetRef.current!, [new File(['a'], 'dropped.png')])
        pasteInto(document.querySelector('textarea')!, [new File(['a'], 'pasted.png')], '')

        expect(logic.values.attachments).toEqual([])
        // The browser would otherwise open the dropped file and lose the draft.
        expect(notPrevented).toBe(false)
    })

    it('stops listening once unmounted, so a later drop stages nothing', () => {
        renderWithDropTarget()
        const target = dropTargetRef.current!
        cleanup()

        dropFiles(target, [new File(['a'], 'late.png')])

        expect(logic.values.attachments).toEqual([])
    })
})
