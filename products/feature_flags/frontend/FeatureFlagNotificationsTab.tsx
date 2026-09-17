import { FeatureFlagsTab } from 'scenes/feature-flags/featureFlagsLogic'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { NotificationsPane, NotificationsPaneTrigger } from 'scenes/hog-functions/list/NotificationsPane'
import { urls } from 'scenes/urls'

import { CyclotronJobFiltersType, FeatureFlagType, PropertyFilterType, PropertyOperator } from '~/types'

export interface FeatureFlagNotificationsTabProps {
    featureFlag: FeatureFlagType
}

const ACTIVITY_LOG_EVENT = '$activity_log_entry_created'
const STALE_FLAG_EVENT = '$feature_flag_stale'

// Both events carry the flag id as a string: item_id on activity log entries, flag_id on the stale event.
// Values are lists, the shape the property editor writes for "equals".
function notificationTriggersForFlag(featureFlag: FeatureFlagType): NotificationsPaneTrigger[] {
    const itemId = String(featureFlag.id)
    const changeFilters: CyclotronJobFiltersType = {
        // Keeps the sub-template's own filters, so these also show in the project-wide list
        ...getFiltersFromSubTemplateId('feature-flag-change'),
        properties: [
            { key: 'item_id', type: PropertyFilterType.Event, value: [itemId], operator: PropertyOperator.Exact },
        ],
    }
    const staleFilters: CyclotronJobFiltersType = {
        ...getFiltersFromSubTemplateId('feature-flag-stale'),
        properties: [
            { key: 'flag_id', type: PropertyFilterType.Event, value: [itemId], operator: PropertyOperator.Exact },
        ],
    }
    // The list matches any of these. The activity side panel's Subscribe menu binds the same flag with a
    // different shape (top-level scope, string values), so probe for that too.
    const changeListFilterGroups = [
        {
            events: [
                { id: ACTIVITY_LOG_EVENT, type: 'events', properties: [{ key: 'scope', value: ['FeatureFlag'] }] },
            ],
            properties: [{ key: 'item_id', value: [itemId] }],
        },
        {
            events: [{ id: ACTIVITY_LOG_EVENT, type: 'events' }],
            properties: [
                { key: 'scope', value: 'FeatureFlag' },
                { key: 'item_id', value: itemId },
            ],
        },
        {
            events: [{ id: ACTIVITY_LOG_EVENT, type: 'events' }],
            properties: [
                { key: 'scope', value: ['FeatureFlag'] },
                { key: 'item_id', value: [itemId] },
            ],
        },
    ] as CyclotronJobFiltersType[]
    const staleListFilterGroups = [
        { events: [{ id: STALE_FLAG_EVENT, type: 'events' }], properties: [{ key: 'flag_id', value: [itemId] }] },
    ] as CyclotronJobFiltersType[]

    return [
        {
            subTemplateId: 'feature-flag-change',
            label: 'Flag is enabled, disabled, or otherwise changed',
            filters: changeFilters,
            listFilterGroups: changeListFilterGroups,
        },
        {
            subTemplateId: 'feature-flag-stale',
            label: 'Flag becomes stale',
            filters: staleFilters,
            listFilterGroups: staleListFilterGroups,
        },
    ]
}

export function FeatureFlagNotificationsTab({ featureFlag }: FeatureFlagNotificationsTabProps): JSX.Element | null {
    if (!featureFlag.id) {
        return null
    }

    return (
        <NotificationsPane
            triggers={notificationTriggersForFlag(featureFlag)}
            scopeLabel={featureFlag.key}
            description={`Get notified when the ${featureFlag.key} flag is enabled, disabled, or otherwise changed, or when it becomes stale: not evaluated for 30 days, or fully rolled out with no usage data.`}
            dialogTitle={`New notification for ${featureFlag.key}`}
            emptyText="No notifications set up for this flag yet. Add one to hear about changes to this flag."
            returnTo={`${urls.featureFlag(featureFlag.id)}?tab=${FeatureFlagsTab.NOTIFICATIONS}`}
        />
    )
}
