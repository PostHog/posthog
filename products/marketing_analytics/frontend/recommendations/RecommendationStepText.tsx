import { useActions } from 'kea'

import { Link } from 'lib/lemon-ui/Link'

import {
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationStep,
} from '~/queries/schema/schema-general'

import { recommendationsLogic } from './recommendationsLogic'

export interface RecommendationStepTextProps {
    step: MarketingAnalyticsRecommendationStep
    rule: MarketingAnalyticsRecommendationRule
}

export interface RecommendationStepLink {
    before: string
    url: string
    linkText: string
    after: string
    dataAttr: string
}

export interface TrackedRecommendationStepLink extends RecommendationStepLink {
    onClick: () => void
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

export function useRecommendationStepLink(
    step: MarketingAnalyticsRecommendationStep,
    rule: MarketingAnalyticsRecommendationRule
): TrackedRecommendationStepLink | null {
    const { reportRecommendationsActionClicked } = useActions(recommendationsLogic)
    const link = recommendationStepLink(step)
    return link
        ? { ...link, onClick: () => reportRecommendationsActionClicked('open_step_link', 'instructions', rule) }
        : null
}

export function RecommendationStepText({ step, rule }: RecommendationStepTextProps): JSX.Element {
    const link = useRecommendationStepLink(step, rule)
    if (!link) {
        return <span>{step.text}</span>
    }
    return (
        <span>
            <span>{link.before}</span>
            <Link to={link.url} target="_blank" targetBlankIcon onClick={link.onClick} data-attr={link.dataAttr}>
                {link.linkText}
            </Link>
            <span>{link.after}</span>
        </span>
    )
}
