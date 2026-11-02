import { RecommendationDataGap } from './recommendations'

export function RecommendationDataGapDescription({ gap }: { gap: RecommendationDataGap }): JSX.Element {
    return (
        <>
            Turn on <code translate="no">{gap.table}</code> to {gap.purpose}
        </>
    )
}
