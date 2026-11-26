import { IconLightBulb } from '@posthog/icons'
import { Button, Spinner } from '@posthog/quill'

export function QuillRecommendationsLoading(): JSX.Element {
    return (
        <Button variant="outline" disabledReason="Loading recommendations">
            <IconLightBulb />
            <span>Recommendations</span>
            <Spinner />
        </Button>
    )
}
