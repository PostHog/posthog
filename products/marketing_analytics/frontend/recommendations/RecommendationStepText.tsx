import { Link } from 'lib/lemon-ui/Link'

import { MarketingAnalyticsRecommendationStep } from '~/queries/schema/schema-general'

export function RecommendationStepText({ step }: { step: MarketingAnalyticsRecommendationStep }): JSX.Element {
    const start = step.url && step.linkText ? step.text.indexOf(step.linkText) : -1
    if (!step.url || !step.linkText || start < 0) {
        return <span>{step.text}</span>
    }
    return (
        <span>
            <span>{step.text.slice(0, start)}</span>
            <Link
                to={step.url}
                target="_blank"
                targetBlankIcon
                data-attr={
                    step.url.startsWith('https://ads.google.com/')
                        ? 'marketing-recommendations-step-open-google-ads'
                        : 'marketing-recommendations-step-open-link'
                }
            >
                {step.linkText}
            </Link>
            <span>{step.text.slice(start + step.linkText.length)}</span>
        </span>
    )
}
