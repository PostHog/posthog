import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconAtSign, IconBug, IconDashboard, IconGraph, IconNotebook, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { EmailPreviewThumbnail } from 'lib/components/EmailPreviewThumbnail/EmailPreviewThumbnail'
import { IconAction, IconEvent } from 'lib/lemon-ui/icons'

import { chatContextLogic } from '../../logics/chatContextLogic'

function iconForType(type: string): JSX.Element {
    switch (type) {
        case 'dashboard':
            return <IconDashboard />
        case 'insight':
            return <IconGraph />
        case 'event':
            return <IconEvent />
        case 'action':
            return <IconAction />
        case 'notebook':
            return <IconNotebook />
        case 'error_tracking_issue':
            return <IconBug />
        default:
            return <IconAtSign />
    }
}

interface AttachmentPreviewProps {
    label: string
    html: string
    onRemove?: () => void
}

function AttachmentPreview({ label, html, onRemove }: AttachmentPreviewProps): JSX.Element {
    return (
        <div
            className="relative flex flex-col w-24 shrink-0 rounded border bg-surface-primary overflow-hidden"
            data-attr="posthog-ai-context-attachment"
        >
            <EmailPreviewThumbnail html={html} title={`${label} preview`} size="attachment" className="border-b" />
            <span className="px-1.5 py-1 text-xs truncate" title={label}>
                {label}
            </span>
            {onRemove && (
                <LemonButton
                    size="xxsmall"
                    type="secondary"
                    icon={<IconX className="h-3 w-3" />}
                    onClick={onRemove}
                    tooltip="Remove"
                    aria-label={`Remove ${label}`}
                    className="absolute top-0.5 right-0.5 bg-surface-primary"
                />
            )}
        </div>
    )
}

export interface AttachedContextChipsProps {
    leading?: ReactNode
    taskId?: string
}

/**
 * Removable chips for what `chatContextLogic` says is in this chat. Closing one removes a pick, dismisses a provider's
 * item from a new chat, or takes the chip off a started chat. Providers can keep mandatory context visible with
 * `dismissible: false`. An item with `previewHtml` shows as a thumbnail in a row above the chips.
 * Renders nothing when there is neither context nor a `leading` slot.
 */
export function AttachedContextChips({ leading, taskId }: AttachedContextChipsProps): JSX.Element | null {
    const logic = chatContextLogic({ taskId })
    const { chips, attachments } = useValues(logic)
    const { removeChip } = useActions(logic)

    if (chips.length === 0 && attachments.length === 0 && !leading) {
        return null
    }

    return (
        <div className="flex flex-col gap-2 min-w-0">
            {attachments.length > 0 && (
                <div className="flex gap-2 overflow-x-auto" data-attr="posthog-ai-context-attachments">
                    {attachments.map(({ chip, previewHtml }) => (
                        <AttachmentPreview
                            key={chip.id}
                            label={chip.label}
                            html={previewHtml}
                            onRemove={chip.dismissible === false ? undefined : () => removeChip(chip)}
                        />
                    ))}
                </div>
            )}
            {(leading || chips.length > 0) && (
                <div className="flex flex-wrap items-center gap-1 min-w-0">
                    {leading}
                    {chips.map((chip) => {
                        const removable = chip.dismissible !== false
                        return (
                            <Tooltip key={chip.id} title={chip.label}>
                                <LemonTag
                                    icon={iconForType(chip.type)}
                                    onClose={removable ? () => removeChip(chip) : undefined}
                                    closable={removable}
                                    closeOnClick={removable}
                                    className="flex items-center text-secondary max-w-48"
                                >
                                    <span className="truncate min-w-0 flex-1">{chip.label}</span>
                                </LemonTag>
                            </Tooltip>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
