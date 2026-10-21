import { EarlyAccessFeatureType, PropertyFilterType, PropertyOperator } from '~/types'

import { MessageAudience } from 'products/workflows/frontend/MessageAudience/messageAudience'
import { draftMessage } from 'products/workflows/frontend/MessageAudience/messageDrafts'

export function enrolledPeopleAudience(earlyAccessFeature: EarlyAccessFeatureType, source: string): MessageAudience {
    const flagKey = earlyAccessFeature.feature_flag.key
    return {
        source,
        properties: [
            {
                key: `$feature_enrollment/${flagKey}`,
                type: PropertyFilterType.Person,
                operator: PropertyOperator.Exact,
                value: ['true'],
            },
        ],
        broadcastName: `${earlyAccessFeature.name} is now available`,
        broadcastEmail: draftMessage({
            kind: 'feature_available',
            featureName: earlyAccessFeature.name,
            featureDescription: earlyAccessFeature.description,
        }),
        workflowEmail: draftMessage({
            kind: 'feature_enrolled',
            featureName: earlyAccessFeature.name,
            featureDescription: earlyAccessFeature.description,
        }),
        draftSource: { source: 'early_access', source_id: earlyAccessFeature.id },
        workflowTrigger: {
            type: 'event',
            filters: {
                events: [
                    {
                        id: '$feature_enrollment_update',
                        name: '$feature_enrollment_update',
                        type: 'events',
                        order: 0,
                        properties: [
                            {
                                key: '$feature_flag',
                                value: [flagKey],
                                operator: PropertyOperator.Exact,
                                type: PropertyFilterType.Event,
                            },
                            // posthog-js sends a boolean here. Exact compiles to a string compare until the project
                            // has a Boolean definition for this property, so it would never match. Contains
                            // compares the stringified value, which works with or without that definition.
                            {
                                key: '$feature_enrollment',
                                value: 'true',
                                operator: PropertyOperator.IContains,
                                type: PropertyFilterType.Event,
                            },
                        ],
                    },
                ],
            },
        },
    }
}
