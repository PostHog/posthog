import { IconLightBulb } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { QuillRecommendationsConnectGoogleAdsButton } from './QuillRecommendationsConnectGoogleAdsButton'
import { recommendationsIdleCopy, RecommendationsIdleState } from './RecommendationsIdle'

export function QuillRecommendationsIdle({ state }: { state: RecommendationsIdleState }): JSX.Element {
    const { message, disabledReason } = recommendationsIdleCopy(state)

    return (
        <>
            <Button variant="outline" disabledReason={disabledReason}>
                <IconLightBulb />
                <span>Recommendations</span>
            </Button>
            {message && (
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    {message}
                </Text>
            )}
            {state === 'no_connected_source' && (
                <QuillRecommendationsConnectGoogleAdsButton type="secondary" location="section_empty" />
            )}
        </>
    )
}
