import { useActions } from 'kea'

import { IconExternal } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import {
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationStep,
} from '~/queries/schema/schema-general'

import { recommendationsLogic } from './recommendationsLogic'
import { recommendationStepLink } from './RecommendationStepText'

export function QuillRecommendationStepText({
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
            <Button
                variant="link"
                size="inline"
                nativeButton={false}
                render={<LinkPrimitive to={link.url} target="_blank" />}
                onClick={() => reportRecommendationsActionClicked('open_step_link', 'instructions', rule)}
                data-attr={link.dataAttr}
            >
                {link.linkText}
                <IconExternal />
            </Button>
            <span>{link.after}</span>
        </span>
    )
}
