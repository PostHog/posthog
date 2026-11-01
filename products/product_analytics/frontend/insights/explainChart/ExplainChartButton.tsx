import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import type { InsightLogicProps } from '~/types'

import { explainChartLogic } from './explainChartLogic'

export function ExplainChartButton({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { storyAvailable, explainAvailable, story, storyShown, investigating, consentRequested } = useValues(
        explainChartLogic(insightProps)
    )
    const { explainClicked, approveConsent, dismissConsent } = useActions(explainChartLogic(insightProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!explainAvailable && !(storyAvailable && story)) {
        return null
    }
    const label = investigating ? 'Investigating…' : 'Explain this chart'
    return (
        <AIConsentPopoverWrapper
            hidden={!consentRequested}
            ignoreDismissal
            onApprove={approveConsent}
            onDismiss={dismissConsent}
        >
            {todayRailNav ? (
                <span data-quill>
                    <Button
                        variant="outline"
                        size="sm"
                        aria-expanded={storyShown}
                        loading={investigating}
                        onClick={explainClicked}
                        data-attr="explain-chart-toggle"
                    >
                        <IconSparkles />
                        {label}
                    </Button>
                </span>
            ) : (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconSparkles />}
                    active={storyShown}
                    loading={investigating}
                    onClick={explainClicked}
                    data-attr="explain-chart-toggle"
                >
                    {label}
                </LemonButton>
            )}
        </AIConsentPopoverWrapper>
    )
}
