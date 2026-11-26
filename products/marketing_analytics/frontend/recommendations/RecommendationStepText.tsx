import { useActions } from 'kea'

import { Link } from 'lib/lemon-ui/Link'

import {
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationStep,
} from '~/queries/schema/schema-general'

import { recommendationsLogic } from './recommendationsLogic'

export interface RecommendationStepLink {
    before: string
    url: string
    linkText: string
    after: string
    dataAttr: string
}

export function recommendationStepLink(step: MarketingAnalyticsRecommendationStep): RecommendationStepLink | null {
    const start = step.url && step.linkText ? step.text.indexOf(step.linkText) : -1
    if (!step.url || !step.linkText || start < 0) {
        return null
    }
    return {
        before: step.text.slice(0, start),
        url: step.url,
        linkText: step.linkText,
        after: step.text.slice(start + step.linkText.length),
        dataAttr: step.url.startsWith('https://ads.google.com/')
            ? 'marketing-recommendations-step-open-google-ads'
            : 'marketing-recommendations-step-open-link',
    }
}

export function RecommendationStepText({
    step,
    rule,
}: {
    step: MarketingAnalyticsRecommendationStep
    rule: MarketingAnalyticsRecommendationRule
}): JSX.Element {
    const { reportRecommendationsActionClicked } = useActions(recommendationsLogic)
    const link = recommendationStepLink(step)
    if (!link) {
        return <span>{step.text}</span>
    }
    return (
        <span>
            <span>{link.before}</span>
            <Link
                to={link.url}
                target="_blank"
                targetBlankIcon
                onClick={() => reportRecommendationsActionClicked('open_step_link', 'instructions', rule)}
                data-attr={link.dataAttr}
            >
                {link.linkText}
            </Link>
            <span>{link.after}</span>
        </span>
    )
}
