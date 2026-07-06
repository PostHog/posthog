import { useActions, useValues } from 'kea'

import { IconAtSign, IconBug, IconDashboard, IconGraph, IconNotebook } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

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

/**
 * The composer's context affordance: an @-button (TaxonomicPopover) that attaches entity refs to
 * `contextPickerLogic`, plus removable chips for everything currently in
 * `attachedContextLogic.contextItems` — picked items and auto-registered providers (e.g. the scene
 * bridge) alike. Closing a picked chip removes it from the picker; closing any other provider's chip
 * dismisses its key, which sticks even when the provider re-registers the item.
 */
export function AttachedContextBar(): JSX.Element {
    const { contextItems, hasContext } = useValues(attachedContextLogic)
    const { dismissContext } = useActions(attachedContextLogic)
    const { pickedKeys } = useValues(contextPickerLogic)
    const { handleTaxonomicFilterChange, removePickedItem } = useActions(contextPickerLogic)

    return (
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
            {contextItems.map((item) => {
                const key = attachedContextItemKey(item)
                const label = labelForItem(item)
                return (
                    <Tooltip key={key} title={label}>
                        <LemonTag
                            icon={iconForType(item.type)}
                            onClose={() => (pickedKeys.has(key) ? removePickedItem(key) : dismissContext(key))}
                            closable
                            closeOnClick
                            className="flex items-center text-secondary max-w-48"
                        >
                            <span className="truncate min-w-0 flex-1">{label}</span>
                        </LemonTag>
                    </Tooltip>
                )
            })}
        </div>
    )
}
