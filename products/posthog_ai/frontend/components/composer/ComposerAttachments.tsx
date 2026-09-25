import { useActions, useValues } from 'kea'
import { type ClipboardEvent, type RefObject, useCallback, useEffect, useState } from 'react'

import { IconDocument, IconImage, IconUpload } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { composerAttachmentsLogic } from '../../logics/composerAttachmentsLogic'
import { MAX_ATTACHMENTS_PER_MESSAGE, formatFileSize, isImageAttachment } from '../../utils/attachments'

/**
 * Resets `LemonFileInput`'s internal mirror of `value` after every pick, so its `onChange` reports only the
 * files just added and the logic stays the one list. Must be a stable reference: a fresh `[]` per render
 * would reset that mirror every render and spin.
 */
const NO_FILES: File[] = []

/** The bytes are already in the browser, so this preview costs an object URL and no request. */
function AttachmentThumbnail({ file }: { file: File }): JSX.Element {
    const [src, setSrc] = useState<string | null>(null)
    useEffect(() => {
        const objectUrl = URL.createObjectURL(file)
        setSrc(objectUrl)
        return () => URL.revokeObjectURL(objectUrl)
    }, [file])

    if (!src) {
        return <IconImage />
    }
    return <img src={src} alt="" className="size-4 rounded-sm object-cover" />
}

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
    const logic = composerAttachmentsLogic({ attachmentsKey })
    const { attachments, uploading, isAtAttachmentLimit } = useValues(logic)
    const { addFiles, removeAttachment } = useActions(logic)

    const addDisabledReason =
        disabledReason ?? (isAtAttachmentLimit ? `Up to ${MAX_ATTACHMENTS_PER_MESSAGE} files per message` : undefined)

    return (
        <div className="flex flex-wrap items-center gap-1 min-w-0">
            <LemonFileInput
                multiple
                // The harness reads the artifact off disk with its own file tools, so narrowing here would
                // only refuse files that work.
                accept="*/*"
                value={NO_FILES}
                onChange={addFiles}
                alternativeDropTargetRef={dropTargetRef}
                showUploadedFiles={false}
                disabledReason={addDisabledReason}
                callToAction={
                    <LemonButton
                        size="xxsmall"
                        type="tertiary"
                        className="flex-shrink-0 border"
                        icon={<IconUpload className="text-secondary" />}
                        disabledReason={addDisabledReason}
                        tooltip="Attach files for PostHog AI to read"
                        data-attr="posthog-ai-attach-file"
                    >
                        {attachments.length > 0 ? null : <span className="text-secondary">Attach</span>}
                    </LemonButton>
                }
            />
            {attachments.map(({ id, file }) => (
                <Tooltip key={id} title={`${file.name} (${formatFileSize(file.size)})`}>
                    <LemonTag
                        icon={
                            uploading ? (
                                <Spinner />
                            ) : isImageAttachment(file.name) ? (
                                <AttachmentThumbnail file={file} />
                            ) : (
                                <IconDocument />
                            )
                        }
                        onClose={() => removeAttachment(id)}
                        closable={!uploading}
                        closeOnClick={!uploading}
                        className="flex items-center text-secondary max-w-48"
                        data-attr="posthog-ai-attachment-chip"
                    >
                        <span className="truncate min-w-0 flex-1">{file.name}</span>
                    </LemonTag>
                </Tooltip>
            ))}
        </div>
    )
}

/** A paste with no files falls through untouched, so pasting text still behaves as text. */
export function useComposerAttachmentPaste(attachmentsKey: string): (event: ClipboardEvent) => void {
    const { addFiles } = useActions(composerAttachmentsLogic({ attachmentsKey }))
    return useCallback(
        (event: ClipboardEvent) => {
            const files = Array.from(event.clipboardData?.files ?? [])
            if (files.length === 0) {
                return
            }
            event.preventDefault()
            addFiles(files)
        },
        [addFiles]
    )
}
