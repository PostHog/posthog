import { IconInfo } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { RecommendationsActionLocation } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { RecommendationDataGapList } from './RecommendationDataGapList'
import { RecommendationDataGap } from './recommendations'

export function RecommendationDataGapButton({
    gaps,
    dataAttr,
    location,
}: {
    gaps: RecommendationDataGap[]
    dataAttr: string
    location: RecommendationsActionLocation
}): JSX.Element {
    return (
        <LemonDropdown
            closeOnClickInside={false}
            overlay={<RecommendationDataGapList gaps={gaps} location={location} />}
        >
            <LemonButton
                size="small"
                type="tertiary"
                icon={<IconInfo />}
                sideIcon={<LemonBadge.Number count={gaps.length} status="muted" />}
                data-attr={dataAttr}
            >
                Improve recommendations
            </LemonButton>
        </LemonDropdown>
    )
}
