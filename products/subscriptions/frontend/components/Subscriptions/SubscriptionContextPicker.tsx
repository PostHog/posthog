import { IconDashboard, IconGraph } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { IconEvent } from 'lib/lemon-ui/icons'

import type { SubscriptionContextApi, SubscriptionContextItemApi } from '../../generated/api.schemas'

const CONTEXT_GROUP_TYPES = [
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.Insights,
    TaxonomicFilterGroupType.Dashboards,
]
const MAX_CONTEXTS = 25

interface PickableContextItem {
    id?: number
    name?: string | null
    derived_name?: string | null
    short_id?: string
}

interface SubscriptionContextPickerProps {
    contexts: SubscriptionContextApi[]
    contextItems: SubscriptionContextItemApi[]
    onAdd: (context: SubscriptionContextApi) => void
    onAddEvent: (eventName: string) => void
    onRemove: (context: SubscriptionContextApi) => void
    onRemoveEvent: (eventName: string) => void
}

export function SubscriptionContextPicker({
    contexts,
    contextItems,
    onAdd,
    onAddEvent,
    onRemove,
    onRemoveEvent,
}: SubscriptionContextPickerProps): JSX.Element {
    const eventNames = contextItems
        .filter(
            (item): item is SubscriptionContextItemApi & { kind: 'event'; event_name: string } => item.kind === 'event'
        )
        .map((item) => item.event_name)

    const handleChange = (
        value: string | number,
        groupType: TaxonomicFilterGroupType,
        item: PickableContextItem
    ): void => {
        if (groupType === TaxonomicFilterGroupType.Events && typeof value === 'string' && value) {
            onAddEvent(value)
            return
        }
        if (typeof item.id !== 'number') {
            return
        }
        if (groupType === TaxonomicFilterGroupType.Dashboards) {
            onAdd({
                kind: 'dashboard',
                id: item.id,
                name: item.name || 'Dashboard',
                url: `/dashboard/${item.id}`,
            })
        } else if (groupType === TaxonomicFilterGroupType.Insights) {
            onAdd({
                kind: 'insight',
                id: item.id,
                name: item.name || item.derived_name || 'Insight',
                url: `/insights/${item.short_id || value}`,
            })
        }
    }

    return (
        <div className="flex flex-wrap items-center gap-1 min-w-0">
            <TaxonomicPopover
                groupType={TaxonomicFilterGroupType.Insights}
                groupTypes={CONTEXT_GROUP_TYPES}
                onChange={handleChange}
                closeOnChange={false}
                placeholder="Add context"
                size="small"
                type="secondary"
                width={450}
                data-attr="ai-subscription-context-picker"
                disabledReason={
                    contexts.length + contextItems.length >= MAX_CONTEXTS
                        ? `You can add up to ${MAX_CONTEXTS} context items`
                        : undefined
                }
            />
            {eventNames.map((eventName) => (
                <Tooltip key={`event:${eventName}`} title={eventName}>
                    <LemonTag
                        icon={<IconEvent />}
                        onClose={() => onRemoveEvent(eventName)}
                        closable
                        className="flex items-center text-secondary max-w-48"
                        data-attr="ai-subscription-context"
                    >
                        <Link
                            to={`/data-management/events/${encodeURIComponent(eventName)}`}
                            target="_blank"
                            className="truncate min-w-0 flex-1"
                        >
                            {eventName}
                        </Link>
                    </LemonTag>
                </Tooltip>
            ))}
            {contexts.map((context) => (
                <Tooltip key={`${context.kind}:${context.id}`} title={context.name}>
                    <LemonTag
                        icon={context.kind === 'dashboard' ? <IconDashboard /> : <IconGraph />}
                        onClose={() => onRemove(context)}
                        closable
                        className="flex items-center text-secondary max-w-48"
                        data-attr="ai-subscription-context"
                    >
                        <Link to={context.url} target="_blank" className="truncate min-w-0 flex-1">
                            {context.name}
                        </Link>
                    </LemonTag>
                </Tooltip>
            ))}
        </div>
    )
}
