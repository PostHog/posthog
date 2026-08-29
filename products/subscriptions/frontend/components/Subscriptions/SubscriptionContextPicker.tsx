import { IconDashboard, IconGraph, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import type {
    SubscriptionContextApi,
    SubscriptionDashboardContextApi,
    SubscriptionInsightContextApi,
} from 'products/subscriptions/frontend/generated/api.schemas'

import { MAX_CONTEXTS } from './utils'

const CONTEXT_GROUP_TYPES = [TaxonomicFilterGroupType.Dashboards, TaxonomicFilterGroupType.Insights]

interface PickableContextItem {
    id?: number
    name?: string | null
    derived_name?: string | null
    short_id?: string
}

interface SubscriptionContextPickerProps {
    contexts: SubscriptionContextApi[]
    onAdd: (context: SubscriptionContextApi) => void
    onRemove: (context: SubscriptionContextApi) => void
}

function isDashboardContext(context: SubscriptionContextApi): context is SubscriptionDashboardContextApi {
    return 'dashboard_id' in context
}

function isInsightContext(context: SubscriptionContextApi): context is SubscriptionInsightContextApi {
    return 'insight_id' in context
}

export function SubscriptionContextPicker({ contexts, onAdd, onRemove }: SubscriptionContextPickerProps): JSX.Element {
    const handleChange = (
        value: string | number,
        groupType: TaxonomicFilterGroupType,
        item: PickableContextItem
    ): void => {
        if (typeof item.id !== 'number') {
            return
        }
        if (groupType === TaxonomicFilterGroupType.Dashboards) {
            onAdd({
                dashboard_id: item.id,
                dashboard_name: item.name || 'Untitled dashboard',
            })
        } else if (groupType === TaxonomicFilterGroupType.Insights) {
            onAdd({
                insight_id: item.id,
                insight_short_id: item.short_id || String(value),
                insight_name: item.name || item.derived_name || 'Untitled insight',
            })
        }
    }

    const disabledReason =
        contexts.length >= MAX_CONTEXTS
            ? `You can add up to ${MAX_CONTEXTS} dashboards and insights. Remove one to add another.`
            : undefined

    return (
        <div className="flex flex-wrap items-center gap-1 min-w-0" data-attr="ai-subscription-context-list">
            <TaxonomicPopover
                groupType={TaxonomicFilterGroupType.Dashboards}
                groupTypes={CONTEXT_GROUP_TYPES}
                onChange={handleChange}
                selectedProperties={{
                    [TaxonomicFilterGroupType.Dashboards]: contexts
                        .filter(isDashboardContext)
                        .map((context) => context.dashboard_id),
                    [TaxonomicFilterGroupType.Insights]: contexts
                        .filter(isInsightContext)
                        .map((context) => context.insight_short_id),
                }}
                closeOnChange={contexts.length === MAX_CONTEXTS - 1}
                placeholder="Add context"
                size="small"
                type="secondary"
                width={400}
                data-attr="ai-subscription-context-picker"
                disabledReason={disabledReason}
            />
            {contexts.map((context) => {
                const isDashboard = isDashboardContext(context)
                const name = isDashboard ? context.dashboard_name : context.insight_name
                const url = isDashboard ? `/dashboard/${context.dashboard_id}` : `/insights/${context.insight_short_id}`
                const key = isDashboard ? `dashboard:${context.dashboard_id}` : `insight:${context.insight_id}`

                return (
                    <Tooltip key={key} title={name}>
                        <LemonTag
                            icon={isDashboard ? <IconDashboard /> : <IconGraph />}
                            className="flex items-center text-secondary max-w-48"
                            data-attr="ai-subscription-context"
                        >
                            <Link to={url} target="_blank" className="truncate min-w-0 flex-1">
                                {name}
                            </Link>
                            <LemonButton
                                icon={<IconX />}
                                onClick={() => onRemove(context)}
                                aria-label={`Remove ${name}`}
                                size="xsmall"
                                className="LemonTag__right-button"
                            />
                        </LemonTag>
                    </Tooltip>
                )
            })}
        </div>
    )
}
