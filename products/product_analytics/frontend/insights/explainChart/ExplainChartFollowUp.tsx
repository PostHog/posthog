import { IconMessage } from '@posthog/icons'
import { Button } from '@posthog/quill'

export function ExplainChartFollowUp({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <Button variant="link-muted" size="xs" onClick={onClick} data-attr="explain-chart-ask-follow-up">
            <IconMessage />
            Ask PostHog AI a follow-up
        </Button>
    )
}
