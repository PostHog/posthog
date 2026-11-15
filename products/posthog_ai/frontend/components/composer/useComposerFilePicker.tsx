import { useActions, useValues } from 'kea'
import { type ChangeEvent, type RefObject, useCallback, useRef } from 'react'

import { composerAttachmentsLogic } from '../../logics/composerAttachmentsLogic'
import { MAX_ATTACHMENTS_PER_MESSAGE } from '../../utils/attachments'
import { useFileDrop } from './useFileDrop'

export interface ComposerFilePicker {
    fileInput: JSX.Element
    openPicker: () => void
    isOver: boolean
    addDisabledReason: string | undefined
    hasStagedFiles: boolean
}

export function useComposerFilePicker(
    attachmentsKey: string,
    dropTargetRef?: RefObject<HTMLElement>,
    disabledReason?: string
): ComposerFilePicker {
    const logic = composerAttachmentsLogic({ attachmentsKey })
    const { stagedAttachments, isAtAttachmentLimit } = useValues(logic)
    const { addFiles } = useActions(logic)
    const inputRef = useRef<HTMLInputElement>(null)

    const addDisabledReason =
        disabledReason ?? (isAtAttachmentLimit ? `Up to ${MAX_ATTACHMENTS_PER_MESSAGE} files per message` : undefined)

    const acceptDropped = useCallback(
        (files: File[]) => {
            if (!addDisabledReason) {
                addFiles(files)
            }
        },
        [addFiles, addDisabledReason]
    )
    const isOver = useFileDrop(dropTargetRef, acceptDropped)

    const onPicked = (event: ChangeEvent<HTMLInputElement>): void => {
        const files = Array.from(event.target.files ?? [])
        if (files.length > 0) {
            addFiles(files)
        }
        // Or picking the same file twice in a row is not a change and never fires.
        event.target.value = ''
    }

    const fileInput = (
        <input
            ref={inputRef}
            type="file"
            multiple
            // The harness reads the artifact off disk with its own file tools, so narrowing here would
            // only refuse files that work.
            accept="*/*"
            className="hidden"
            onChange={onPicked}
            data-attr="posthog-ai-attach-input"
        />
    )

    return {
        fileInput,
        openPicker: () => inputRef.current?.click(),
        isOver,
        addDisabledReason,
        hasStagedFiles: stagedAttachments.length > 0,
    }
}
