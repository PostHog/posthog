import { useRef } from 'react'

import { IconLightBulb } from '@posthog/icons'
import { Button, Popover, PopoverContent, Spinner, Text } from '@posthog/quill'

import { RecommendationsShownState } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { QuillRecommendationsIdle } from './QuillRecommendationsIdle'
import { QuillRecommendationsSummary } from './QuillRecommendationsSummary'

export function QuillRecommendationsSection({
    shownState,
    showIntro,
    onDismissIntro,
    onOpenFirstRule,
    error,
    modal,
}: {
    shownState: RecommendationsShownState | null
    showIntro: boolean
    onDismissIntro: () => void
    onOpenFirstRule: (source: 'intro' | 'button') => void
    error: JSX.Element | null
    modal: JSX.Element
}): JSX.Element {
    const summaryRef = useRef<HTMLDivElement>(null)

    return (
        <div className="@container flex flex-col gap-3 pt-2" data-attr="marketing-recommendations">
            <div ref={summaryRef} className="flex min-w-0 flex-wrap items-center gap-2">
                {shownState === 'recommendations' ? (
                    <QuillRecommendationsSummary onOpen={() => onOpenFirstRule('button')} />
                ) : shownState === null ? (
                    <Button variant="outline" disabledReason="Loading recommendations">
                        <IconLightBulb />
                        <span>Recommendations</span>
                        <Spinner />
                    </Button>
                ) : (
                    <QuillRecommendationsIdle state={shownState} />
                )}
            </div>
            <Popover open={showIntro}>
                <PopoverContent anchor={summaryRef} side="bottom" align="start" arrow className="gap-2">
                    <Text size="xs" weight="semibold" render={<strong className="m-0" />}>
                        New: recommendations
                    </Text>
                    <Text size="xs" render={<p className="m-0" />}>
                        Built from your Google Ads and Google Search Console data. They show where to cut wasted spend,
                        where to grow, and which pages to improve for organic search. They are suggestions, so check
                        each one before you edit a campaign.
                    </Text>
                    <div className="flex flex-wrap justify-end gap-2">
                        <Button onClick={onDismissIntro}>Got it</Button>
                        <Button
                            variant="primary"
                            onClick={() => onOpenFirstRule('intro')}
                            data-attr="marketing-recommendations-intro-open"
                        >
                            See recommendations
                        </Button>
                    </div>
                </PopoverContent>
            </Popover>
            {error}
            {modal}
        </div>
    )
}
