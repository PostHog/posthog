import { IconExternal } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { RecommendationStepTextProps, useRecommendationStepLink } from './RecommendationStepText'

export function QuillRecommendationStepText({ step, rule }: RecommendationStepTextProps): JSX.Element {
    const link = useRecommendationStepLink(step, rule)
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
                onClick={link.onClick}
                data-attr={link.dataAttr}
            >
                {link.linkText}
                <IconExternal />
            </Button>
            <span>{link.after}</span>
        </span>
    )
}
