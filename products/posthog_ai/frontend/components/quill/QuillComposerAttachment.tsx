import { IconX } from '@posthog/icons'
import { Button, Spinner, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

import { formatFileSize } from '../../utils/attachments'
import type { ComposerAttachmentProps } from '../composer/ComposerAttachment'
import { ComposerAttachmentPreview } from '../composer/ComposerAttachmentPreview'

export function QuillComposerAttachment({ file, uploading, onRemove }: ComposerAttachmentProps): JSX.Element {
    return (
        <div
            data-quill
            className="group/attachment relative shrink-0 hover:z-10 focus-within:z-10"
            data-attr="posthog-ai-attachment-chip"
        >
            <Tooltip>
                <TooltipTrigger
                    render={
                        <span
                            tabIndex={0}
                            role="img"
                            aria-label={file.name}
                            aria-busy={uploading}
                            className="relative flex size-8 items-center justify-center overflow-hidden rounded-md border border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)]"
                        >
                            <ComposerAttachmentPreview file={file} />
                            {uploading && (
                                <span className="absolute inset-0 flex items-center justify-center bg-[var(--muted)]/80">
                                    <Spinner className="size-4" />
                                </span>
                            )}
                        </span>
                    }
                />
                <TooltipContent>{`${file.name} (${formatFileSize(file.size)})`}</TooltipContent>
            </Tooltip>
            {!uploading && (
                <Button
                    type="button"
                    variant="secondary"
                    size="icon-xs"
                    aria-label={`Remove ${file.name}`}
                    onClick={(event) => {
                        event.stopPropagation()
                        onRemove()
                    }}
                    className="absolute -top-1.5 -right-1.5 z-10 rounded-full opacity-0 group-hover/attachment:opacity-100 group-focus-within/attachment:opacity-100 focus-visible:opacity-100"
                    data-attr="posthog-ai-remove-attachment"
                >
                    <IconX />
                </Button>
            )}
        </div>
    )
}
