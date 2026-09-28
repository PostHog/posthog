import { useActions, useValues } from 'kea'

import { IconAtSign, IconBug, IconDashboard, IconGraph, IconNotebook, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { EmailPreviewThumbnail } from 'lib/components/EmailPreviewThumbnail/EmailPreviewThumbnail'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { IconAction, IconEvent } from 'lib/lemon-ui/icons'

import { attachedContextLogic } from '../../logics/attachedContextLogic'
import { contextPickerLogic } from '../../logics/contextPickerLogic'
import { type AttachedContextItem, attachedContextItemKey } from '../../types/contextTypes'

const PICKER_GROUP_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.Actions,
    TaxonomicFilterGroupType.Insights,
    TaxonomicFilterGroupType.Dashboards,
    TaxonomicFilterGroupType.Notebooks,
    TaxonomicFilterGroupType.ErrorTrackingIssues,
]

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

function labelForItem(item: AttachedContextItem): string {
    if (item.label) {
        return item.label
    }
    if (item.type === 'text') {
        return item.value ?? 'Text'
    }
    return `${item.type} ${item.key ?? ''}`.trim()
}

interface AttachmentPreviewProps {
    label: string
    html: string
    onRemove?: () => void
}

/** An attached item with a preview, shown as a thumbnail with its name, like an image attachment in a chat composer. */
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

/**
 * The composer's context affordance: an @-button (TaxonomicPopover) that attaches entity refs to
 * `contextPickerLogic`, plus removable chips for everything currently in
 * `attachedContextLogic.contextItems` — picked items and auto-registered providers (e.g. the scene
 * bridge) alike. Closing a dismissible picked chip removes it from the picker; closing any other
 * dismissible provider's chip dismisses its key, which sticks even when the provider re-registers
 * the item. Providers can keep mandatory context visible with `dismissible: false`.
 * An item with `previewHtml` shows as a thumbnail in a row above the chips instead of as a chip.
 */
export function AttachedContextBar(): JSX.Element {
    const { contextItems, hasContext } = useValues(attachedContextLogic)
    const { dismissContext } = useActions(attachedContextLogic)
    const { pickedKeys } = useValues(contextPickerLogic)
    const { handleTaxonomicFilterChange, removePickedItem } = useActions(contextPickerLogic)

    const visibleItems = contextItems.filter((item) => !item.hidden)
    const attachments = visibleItems.filter((item) => item.previewHtml)
    const chips = visibleItems.filter((item) => !item.previewHtml)
    const removeItem = (item: AttachedContextItem): (() => void) | undefined => {
        if (item.dismissible === false) {
            return undefined
        }
        const key = attachedContextItemKey(item)
        return () => (pickedKeys.has(key) ? removePickedItem(key) : dismissContext(key, item.dismissGroup))
    }

    return (
        <div className="flex flex-col gap-2 min-w-0">
            {attachments.length > 0 && (
                <div className="flex gap-2 overflow-x-auto" data-attr="posthog-ai-context-attachments">
                    {attachments.map((item) => (
                        <AttachmentPreview
                            key={attachedContextItemKey(item)}
                            label={labelForItem(item)}
                            html={item.previewHtml!}
                            onRemove={removeItem(item)}
                        />
                    ))}
                </div>
            )}
            <div className="flex flex-wrap items-center gap-1 min-w-0">
                <Tooltip title="Add context to help PostHog AI answer your question">
                    {/* Wrapper span prevents Base UI's Tooltip.Trigger from merging
                    props into TaxonomicPopover. Without it, mergeProps treats
                    onChange as a DOM event handler and wraps it in a single-arg
                    callback, dropping the groupType and item arguments. */}
                    <span>
                        <TaxonomicPopover
                            size="xxsmall"
                            type="tertiary"
                            className="flex-shrink-0 border"
                            groupType={TaxonomicFilterGroupType.Events}
                            groupTypes={PICKER_GROUP_TYPES}
                            onChange={handleTaxonomicFilterChange}
                            icon={<IconAtSign className="text-secondary" />}
                            placeholder={hasContext ? null : 'Add context'}
                            placeholderClass="text-secondary"
                            width={450}
                            data-attr="posthog-ai-context-picker"
                        />
                    </span>
                </Tooltip>
                {chips.map((item) => {
                    const key = attachedContextItemKey(item)
                    const label = labelForItem(item)
                    const onRemove = removeItem(item)
                    return (
                        <Tooltip key={key} title={label}>
                            <LemonTag
                                icon={iconForType(item.type)}
                                onClose={onRemove}
                                closable={!!onRemove}
                                closeOnClick={!!onRemove}
                                className="flex items-center text-secondary max-w-48"
                            >
                                <span className="truncate min-w-0 flex-1">{label}</span>
                            </LemonTag>
                        </Tooltip>
                    )
                })}
            </div>
        </div>
    )
}
