import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

import { EmailPreviewThumbnail } from 'lib/components/EmailPreviewThumbnail/EmailPreviewThumbnail'

import { chatContextLogic } from '../../logics/chatContextLogic'
import { QuillAttachedContextChip } from './QuillAttachedContextChip'

export interface QuillAttachedContextChipsProps {
    taskId?: string
}

export function QuillAttachedContextChips({ taskId }: QuillAttachedContextChipsProps): JSX.Element | null {
    const logic = chatContextLogic({ taskId })
    const { chips, attachments } = useValues(logic)
    const { removeChip } = useActions(logic)

    if (chips.length === 0 && attachments.length === 0) {
        return null
    }

    return (
        <>
            {attachments.length > 0 && (
                <div className="flex w-full gap-2 overflow-x-auto" data-attr="posthog-ai-context-attachments">
                    {attachments.map(({ chip, previewHtml }) => (
                        <div
                            key={chip.id}
                            className="relative flex w-24 shrink-0 flex-col overflow-hidden rounded border bg-surface-primary"
                            data-attr="posthog-ai-context-attachment"
                        >
                            <EmailPreviewThumbnail
                                html={previewHtml}
                                title={`${chip.label} preview`}
                                size="attachment"
                                className="border-b"
                            />
                            <span className="truncate px-1.5 py-1 text-xs" title={chip.label}>
                                {chip.label}
                            </span>
                            {chip.dismissible !== false && (
                                <Button
                                    size="icon-xs"
                                    aria-label={`Remove ${chip.label}`}
                                    onClick={() => removeChip(chip)}
                                    className="absolute top-0.5 right-0.5"
                                >
                                    <IconX />
                                </Button>
                            )}
                        </div>
                    ))}
                </div>
            )}
            {chips.map((chip) => (
                <QuillAttachedContextChip
                    key={chip.id}
                    chip={chip}
                    onRemove={chip.dismissible === false ? undefined : () => removeChip(chip)}
                />
            ))}
        </>
    )
}
