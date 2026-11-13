import { useActions } from 'kea'

import { Link } from 'lib/lemon-ui/Link'

import {
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationStep,
} from '~/queries/schema/schema-general'

import { recommendationsLogic } from './recommendationsLogic'

export function RecommendationStepText({
    step,
    rule,
}: {
    step: MarketingAnalyticsRecommendationStep
    rule: MarketingAnalyticsRecommendationRule
}): JSX.Element {
    const { reportRecommendationsActionClicked } = useActions(recommendationsLogic)
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
                onClick={() => reportRecommendationsActionClicked('open_step_link', 'instructions', rule)}
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
