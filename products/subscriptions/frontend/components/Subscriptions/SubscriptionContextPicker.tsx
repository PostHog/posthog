import { IconDashboard, IconGraph } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { IconEvent } from 'lib/lemon-ui/icons'

import type { SubscriptionContextApi, SubscriptionContextItemApi } from '../../generated/api.schemas'
import { MAX_CONTEXTS } from './utils'

const CONTEXT_GROUP_TYPES = [
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.Insights,
    TaxonomicFilterGroupType.Dashboards,
]

interface PickableContextItem {
    id?: number
    name?: string | null
    derived_name?: string | null
    short_id?: string
}

interface SubscriptionContextPickerProps {
    contextCount: number
    contextEnabled: boolean
    contexts: SubscriptionContextApi[]
    contextItems: SubscriptionContextItemApi[]
    onAdd: (context: SubscriptionContextApi) => void
    onAddEvent: (eventName: string) => void
    onRemove: (context: SubscriptionContextApi) => void
    onRemoveEvent: (eventName: string) => void
}

export function SubscriptionContextPicker({
    contextCount,
    contextEnabled,
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
                // Hide the Events tab's "All events" row (value null): it is a no-op here, since a
                // report context is a specific event, dashboard, or insight, not the whole project.
                excludedProperties={{ [TaxonomicFilterGroupType.Events]: [null] }}
                closeOnChange={false}
                placeholder="Add context"
                size="small"
                type="secondary"
                width={450}
                data-attr="ai-subscription-context-picker"
                disabledReason={
                    !contextEnabled
                        ? 'Report context is not enabled for your account.'
                        : contextCount >= MAX_CONTEXTS
                          ? `Context limit reached (${MAX_CONTEXTS}). Remove a context item to add another.`
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
                        {/* Events carry only a name here, and the event-definition route resolves by
                            UUID, so a name-based link dead-ends on "not found". Render plain text. */}
                        <span className="truncate min-w-0 flex-1">{eventName}</span>
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
