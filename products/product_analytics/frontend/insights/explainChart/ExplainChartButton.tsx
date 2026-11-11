import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import type { InsightLogicProps } from '~/types'

import { explainChartLogic } from './explainChartLogic'

export function ExplainChartButton({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const {
        storyAvailable,
        explainAvailable,
        story,
        storyVisible,
        investigating,
        consentRequested,
        explainDisabledReason,
    } = useValues(explainChartLogic(insightProps))
    const { explainClicked, approveConsent, dismissConsent } = useActions(explainChartLogic(insightProps))
    const quillSurface = useQuillSurface()

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
            {quillSurface ? (
                <span data-quill>
                    <Button
                        variant="outline"
                        size="sm"
                        aria-expanded={storyVisible}
                        disabledReason={explainDisabledReason}
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
                    active={storyVisible}
                    disabledReason={explainDisabledReason}
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
