import { IconDashboard, IconGraph } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import type { SubscriptionContextApi } from '../../generated/api.schemas'

const CONTEXT_GROUP_TYPES = [TaxonomicFilterGroupType.Insights, TaxonomicFilterGroupType.Dashboards]
const MAX_CONTEXTS = 25

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
                    contexts.length >= MAX_CONTEXTS ? `You can add up to ${MAX_CONTEXTS} context items` : undefined
                }
            />
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
