import { IconInfo } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { RecommendationsActionLocation } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { QuillRecommendationCountBadge } from './QuillRecommendationCountBadge'
import { QuillRecommendationDataGapList } from './QuillRecommendationDataGapList'
import { RecommendationDataGap } from './recommendations'

export function QuillRecommendationDataGapButton({
    gaps,
    dataAttr,
    location,
}: {
    gaps: RecommendationDataGap[]
    dataAttr: string
    location: RecommendationsActionLocation
}): JSX.Element {
    return (
        <Popover>
            <PopoverTrigger render={<Button data-attr={dataAttr} />}>
                <IconInfo />
                <span>Improve recommendations</span>
                <QuillRecommendationCountBadge count={gaps.length} maxDigits={1} />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-112 max-w-screen">
                <QuillRecommendationDataGapList gaps={gaps} location={location} />
            </PopoverContent>
        </Popover>
    )
}
