import { IconLightBulb } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

export function RecommendationsLoading(): JSX.Element {
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconLightBulb />}
            sideIcon={<Spinner textColored />}
            disabledReason="Loading recommendations"
        >
            Recommendations
        </LemonButton>
    )
}
