import { LemonBanner } from '@posthog/lemon-ui'

export function AiVisibilityReportIntroduction(): JSX.Element {
    return (
        <LemonBanner type="info" className="text-sm">
            Sends the AI visibility report for the last 7 complete days: brand visibility and citation rate on
            non-branded prompts, every topic's change, the pages to watch and up to 3 suggested actions. Weeks without
            answers are skipped.
        </LemonBanner>
    )
}
