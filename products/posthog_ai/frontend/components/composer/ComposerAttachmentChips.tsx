import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconDocument, IconImage } from '@posthog/icons'
import { LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { composerAttachmentsLogic } from '../../logics/composerAttachmentsLogic'
import { formatFileSize, isImageAttachment } from '../../utils/attachments'

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

export function ComposerAttachmentChips({ attachmentsKey }: { attachmentsKey: string }): JSX.Element | null {
    const logic = composerAttachmentsLogic({ attachmentsKey })
    const { stagedAttachments, uploading } = useValues(logic)
    const { removeAttachment } = useActions(logic)
    if (stagedAttachments.length === 0) {
        return null
    }
    return (
        <>
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
        </>
    )
}
