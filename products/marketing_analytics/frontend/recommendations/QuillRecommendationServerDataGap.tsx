import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { RecommendationsActionLocation } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { ServerDataGap } from './recommendations'
import { useServerDataGapAction } from './RecommendationServerDataGap'

export function QuillRecommendationServerDataGap({
    gap,
    location,
}: {
    gap: ServerDataGap
    location: RecommendationsActionLocation
}): JSX.Element {
    const action = useServerDataGapAction(gap, location)
    return (
        <Item variant="outline" size="sm" className="flex-wrap">
            <ItemContent>
                {gap.sourceName && <ItemTitle>{gap.sourceName}</ItemTitle>}
                <ItemDescription>{gap.message}</ItemDescription>
            </ItemContent>
            {action && (
                <ItemActions>
                    <Button
                        variant="outline"
                        render={action.to ? <LinkPrimitive to={action.to} /> : undefined}
                        data-attr={action.dataAttr}
                        onClick={action.onClick}
                    >
                        {action.label}
                    </Button>
                </ItemActions>
            )}
        </Item>
    )
}
