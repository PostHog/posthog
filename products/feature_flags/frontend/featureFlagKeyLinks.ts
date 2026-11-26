import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, FeatureFlagType } from '~/types'

// Deleting a flag that an experiment uses renames its key to `<key>:deleted:<id>`. Code still calls the flag by
// its old key, so that's the key to copy.
export function keyBeforeDelete(featureFlag: FeatureFlagType): string {
    const suffix = `:deleted:${featureFlag.id}`
    return featureFlag.key.endsWith(suffix) ? featureFlag.key.slice(0, -suffix.length) : featureFlag.key
}

export function featureFlagBreakdownInsightUrl(flagKey: string): string {
    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                { event: '$pageview', name: '$pageview', kind: NodeKind.EventsNode, math: BaseMathType.UniqueUsers },
            ],
            breakdownFilter: {
                breakdown_type: 'event',
                breakdown: `$feature/${flagKey}`,
            },
        },
    }
    return urls.insightNew({ query })
}
