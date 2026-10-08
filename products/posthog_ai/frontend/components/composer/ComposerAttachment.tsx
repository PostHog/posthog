import { IconX } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { formatFileSize } from '../../utils/attachments'
import { ComposerAttachmentPreview } from './ComposerAttachmentPreview'

export interface ComposerAttachmentProps {
    file: File
    uploading: boolean
    onRemove: () => void
}

export function ComposerAttachment({ file, uploading, onRemove }: ComposerAttachmentProps): JSX.Element {
    return (
        <div
            className="group/attachment relative shrink-0 hover:z-10 focus-within:z-10"
            data-attr="posthog-ai-attachment-chip"
        >
            <Tooltip title={`${file.name} (${formatFileSize(file.size)})`}>
                <span
                    tabIndex={0}
                    role="img"
                    aria-label={file.name}
                    aria-busy={uploading}
                    className="relative flex size-8 items-center justify-center overflow-hidden rounded border bg-bg-light text-secondary"
                >
                    <ComposerAttachmentPreview file={file} />
                    {uploading && (
                        <span className="absolute inset-0 flex items-center justify-center bg-bg-light/80">
                            <Spinner className="size-4" />
                        </span>
                    )}
                </span>
            </Tooltip>
            {!uploading && (
                <LemonButton
                    size="xxsmall"
                    noPadding
                    icon={<IconX className="size-3" />}
                    aria-label={`Remove ${file.name}`}
                    onClick={(event) => {
                        event.stopPropagation()
                        onRemove()
                    }}
                    className="absolute -top-1.5 -right-1.5 z-10 size-4 min-h-0 rounded-full border bg-bg-light opacity-0 group-hover/attachment:opacity-100 group-focus-within/attachment:opacity-100 focus-visible:opacity-100"
                    data-attr="posthog-ai-remove-attachment"
                />
            )}
        </div>
    )
}
