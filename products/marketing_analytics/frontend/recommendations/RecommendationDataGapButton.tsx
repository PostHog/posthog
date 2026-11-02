import { IconInfo } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { RecommendationDataGapList } from './RecommendationDataGapList'
import { RecommendationDataGap } from './recommendations'

export function RecommendationDataGapButton({
    gaps,
    dataAttr,
}: {
    gaps: RecommendationDataGap[]
    dataAttr: string
}): JSX.Element {
    return (
        <LemonDropdown closeOnClickInside={false} overlay={<RecommendationDataGapList gaps={gaps} />}>
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
