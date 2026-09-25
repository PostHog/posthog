import { useActions, useValues } from 'kea'
import { type ChangeEvent, type ClipboardEvent, type RefObject, useCallback, useEffect, useRef, useState } from 'react'

import { IconDocument, IconImage, IconUpload } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { composerAttachmentsLogic } from '../../logics/composerAttachmentsLogic'
import { MAX_ATTACHMENTS_PER_MESSAGE, formatFileSize, isImageAttachment } from '../../utils/attachments'

/**
 * The single gate on attachments. Every way to stage a file — the button, the drop target, the paste —
 * passes through this module, so a composer that renders it needs no gate of its own.
 */
function useAttachmentsEnabled(): boolean {
    const { featureFlags } = useValues(featureFlagLogic)
    return !!featureFlags[FEATURE_FLAGS.PHAI_TASKS_ATTACHEMENTS]
}

/**
 * Not `LemonFileInput`'s `alternativeDropTargetRef`: it keeps its own copy of the file list and re-syncs it
 * only when the `value` prop changes identity, so a composer whose logic owns the list grows that copy and
 * re-reports every earlier file on each drop.
 */
function useFileDrop(target: RefObject<HTMLElement> | undefined, onFiles: (files: File[]) => void): boolean {
    const [isOver, setIsOver] = useState(false)
    // Dragging over a child fires dragleave on the parent, so count nesting rather than flicker off.
    const depth = useRef(0)
    const onFilesRef = useRef(onFiles)
    onFilesRef.current = onFiles

    useEffect(() => {
        const node = target?.current
        if (!node) {
            return
        }
        const carriesFiles = (event: DragEvent): boolean =>
            Array.from(event.dataTransfer?.types ?? []).includes('Files')
        const onDragEnter = (event: DragEvent): void => {
            if (!carriesFiles(event)) {
                return
            }
            depth.current += 1
            setIsOver(true)
        }
        const onDragOver = (event: DragEvent): void => {
            if (carriesFiles(event)) {
                // Or the browser takes the drop itself and navigates to the file.
                event.preventDefault()
            }
        }
        const onDragLeave = (): void => {
            depth.current = Math.max(0, depth.current - 1)
            if (depth.current === 0) {
                setIsOver(false)
            }
        }
        const onDrop = (event: DragEvent): void => {
            if (!carriesFiles(event)) {
                return
            }
            event.preventDefault()
            depth.current = 0
            setIsOver(false)
            const files = Array.from(event.dataTransfer?.files ?? [])
            if (files.length > 0) {
                onFilesRef.current(files)
            }
        }

        node.addEventListener('dragenter', onDragEnter)
        node.addEventListener('dragover', onDragOver)
        node.addEventListener('dragleave', onDragLeave)
        node.addEventListener('drop', onDrop)
        return () => {
            node.removeEventListener('dragenter', onDragEnter)
            node.removeEventListener('dragover', onDragOver)
            node.removeEventListener('dragleave', onDragLeave)
            node.removeEventListener('drop', onDrop)
        }
    }, [target])

    return isOver
}

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
    const enabled = useAttachmentsEnabled()
    const logic = composerAttachmentsLogic({ attachmentsKey })
    const { stagedAttachments, uploading, isAtAttachmentLimit } = useValues(logic)
    const { addFiles, removeAttachment } = useActions(logic)
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
    const isOver = useFileDrop(enabled ? dropTargetRef : undefined, acceptDropped)

    if (!enabled) {
        return <></>
    }

    const onPicked = (event: ChangeEvent<HTMLInputElement>): void => {
        const files = Array.from(event.target.files ?? [])
        if (files.length > 0) {
            addFiles(files)
        }
        // Or picking the same file twice in a row is not a change and never fires.
        event.target.value = ''
    }

    return (
        <div className="flex flex-wrap items-center gap-1 min-w-0">
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
            <LemonButton
                size="xxsmall"
                type="tertiary"
                className={isOver ? 'flex-shrink-0 border border-accent' : 'flex-shrink-0 border'}
                icon={<IconUpload className="text-secondary" />}
                disabledReason={addDisabledReason}
                tooltip="Attach files for PostHog AI to read"
                onClick={() => inputRef.current?.click()}
                data-attr="posthog-ai-attach-file"
            >
                {stagedAttachments.length > 0 ? null : (
                    <span className="text-secondary">{isOver ? 'Drop to attach' : 'Attach'}</span>
                )}
            </LemonButton>
            {stagedAttachments.map(({ id, file }) => (
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

/**
 * A paste carrying files attaches them. Copying from a spreadsheet or a document puts an image on the
 * clipboard beside the text, so the text is left to the textarea whenever there is any — taking the paste
 * outright would swallow what the user meant to write.
 */
export function useComposerAttachmentPaste(attachmentsKey: string): (event: ClipboardEvent) => void {
    const enabled = useAttachmentsEnabled()
    const { addFiles } = useActions(composerAttachmentsLogic({ attachmentsKey }))
    return useCallback(
        (event: ClipboardEvent) => {
            const files = Array.from(event.clipboardData?.files ?? [])
            if (!enabled || files.length === 0) {
                return
            }
            if (!event.clipboardData?.getData('text/plain')) {
                event.preventDefault()
            }
            addFiles(files)
        },
        [addFiles, enabled]
    )
}
