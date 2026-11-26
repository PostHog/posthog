import { useActions } from 'kea'

import { Button, Item, ItemActions, ItemContent, ItemTitle, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'
import { RecommendationsActionLocation } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { RecommendationDataGapDescription } from './RecommendationDataGapDescription'
import { RecommendationDataGap } from './recommendations'
import { recommendationsLogic } from './recommendationsLogic'

export function QuillRecommendationDataGapList({
    gaps,
    location,
}: {
    gaps: RecommendationDataGap[]
    location: RecommendationsActionLocation
}): JSX.Element {
    const { reportRecommendationsActionClicked } = useActions(recommendationsLogic)
    const sourceIds = [...new Set(gaps.map((gap) => gap.sourceId))]
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
                <Text size="xs" weight="semibold" render={<strong className="m-0" />}>
                    Improve recommendations
                </Text>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Some rules need tables that these sources do not sync yet.
                </Text>
            </div>
            {sourceIds.map((sourceId) => {
                const sourceGaps = gaps.filter((gap) => gap.sourceId === sourceId)
                return (
                    <Item key={sourceId} variant="outline" size="sm" className="flex-wrap">
                        <ItemContent>
                            <ItemTitle>{sourceGaps[0].sourceName}</ItemTitle>
                            <ul className="m-0 flex list-disc flex-col gap-1 pl-4 text-xs text-muted-foreground">
                                {sourceGaps.map((gap) => (
                                    <li key={gap.table}>
                                        <RecommendationDataGapDescription gap={gap} />
                                    </li>
                                ))}
                            </ul>
                        </ItemContent>
                        <ItemActions>
                            <Button
                                variant="outline"
                                render={<LinkPrimitive to={urls.dataWarehouseSource(`managed-${sourceId}`)} />}
                                data-attr="marketing-recommendations-data-gap-manage-source"
                                onClick={() => reportRecommendationsActionClicked('manage_source', location)}
                            >
                                Manage source
                            </Button>
                        </ItemActions>
                    </Item>
                )
            })}
        </div>
    )
}
