import { useActions } from 'kea'
import { type ClipboardEvent, type RefObject, useCallback } from 'react'

import { IconUpload } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { composerAttachmentsLogic } from '../../logics/composerAttachmentsLogic'
import { ComposerAttachmentChips } from './ComposerAttachmentChips'
import { useComposerFilePicker } from './useComposerFilePicker'

export interface ComposerAttachmentsProps {
    attachmentsKey: string
    dropTargetRef?: RefObject<HTMLElement>
    disabledReason?: string
}

export function ComposerAttachments({
    attachmentsKey,
    dropTargetRef,
    disabledReason,
}: ComposerAttachmentsProps): JSX.Element {
    const { fileInput, openPicker, isOver, addDisabledReason, hasStagedFiles } = useComposerFilePicker(
        attachmentsKey,
        dropTargetRef,
        disabledReason
    )

    return (
        <div className="flex flex-wrap items-center gap-1 min-w-0">
            {fileInput}
            <LemonButton
                size="xxsmall"
                type="tertiary"
                className={isOver ? 'flex-shrink-0 border border-accent' : 'flex-shrink-0'}
                icon={<IconUpload className="text-secondary" />}
                disabledReason={addDisabledReason}
                tooltip="Attach files for PostHog AI to read"
                onClick={openPicker}
                data-attr="posthog-ai-attach-file"
            >
                {hasStagedFiles ? null : <span className="text-secondary">{isOver ? 'Drop to attach' : 'Attach'}</span>}
            </LemonButton>
            <ComposerAttachmentChips attachmentsKey={attachmentsKey} />
        </div>
    )
}

/**
 * A paste carrying files attaches them. Copying from a spreadsheet or a document puts an image on the
 * clipboard beside the text, so the text is left to the textarea whenever there is any — taking the paste
 * outright would swallow what the user meant to write.
 */
export function useComposerAttachmentPaste(attachmentsKey: string): (event: ClipboardEvent) => void {
    const { addFiles } = useActions(composerAttachmentsLogic({ attachmentsKey }))
    return useCallback(
        (event: ClipboardEvent) => {
            const files = Array.from(event.clipboardData?.files ?? [])
            if (files.length === 0) {
                return
            }
            if (!event.clipboardData?.getData('text/plain')) {
                event.preventDefault()
            }
            addFiles(files)
        },
        [addFiles]
    )
}
