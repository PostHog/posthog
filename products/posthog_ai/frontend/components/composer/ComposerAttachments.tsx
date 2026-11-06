import { useActions } from 'kea'
import { type ClipboardEvent, type RefObject, useCallback } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { composerAttachmentsLogic } from '../../logics/composerAttachmentsLogic'
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
    const { fileInput, openPicker, isOver, addDisabledReason } = useComposerFilePicker(
        attachmentsKey,
        dropTargetRef,
        disabledReason
    )

    return (
        <>
            {fileInput}
            <LemonButton
                size="xsmall"
                type="tertiary"
                className={isOver ? 'size-6 shrink-0 ring-1 ring-accent' : 'size-6 shrink-0'}
                icon={<IconPlus className="text-secondary" />}
                aria-label="Attach files"
                disabledReason={addDisabledReason}
                tooltip="Attach files for PostHog AI to read"
                onClick={openPicker}
                data-attr="posthog-ai-attach-file"
            />
        </>
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
