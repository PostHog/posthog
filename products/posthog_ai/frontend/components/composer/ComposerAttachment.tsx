import { IconX } from '@posthog/icons'
import { Spinner, Tooltip } from '@posthog/lemon-ui'

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
                <button
                    type="button"
                    aria-label={`Remove ${file.name}`}
                    onClick={(event) => {
                        event.preventDefault()
                        event.stopPropagation()
                        onRemove()
                    }}
                    className="absolute -top-2 -right-2 z-10 flex size-6 items-center justify-center rounded-full border-0 bg-transparent p-1 opacity-0 group-hover/attachment:opacity-100 group-focus-within/attachment:opacity-100 focus-visible:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1"
                    data-attr="posthog-ai-remove-attachment"
                >
                    <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-[var(--color-text-primary)] text-[var(--color-text-primary-inverse)] shadow-sm">
                        <IconX className="size-2.5" />
                    </span>
                </button>
            )}
        </div>
    )
}
