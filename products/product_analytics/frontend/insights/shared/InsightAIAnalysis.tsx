import { useActions, useValues } from 'kea'

import { Button, Heading, Text } from '@posthog/quill'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

export function InsightAIAnalysis(): JSX.Element | null {
    const { insight, insightProps } = useValues(insightLogic)
    const { insightDataLoading } = useValues(insightVizDataLogic(insightProps))
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const quillSurface = useQuillSurface()

    if (!insight.id) {
        return null
    }

    const explain = (): void => openSidePanel(SidePanelTab.Max, '!Explain this insight')
    const disabledReason = insightDataLoading ? 'Please wait for the insight to finish loading' : undefined

    if (quillSurface) {
        return (
            <div className="my-4 flex flex-col gap-2">
                <Heading size="base" render={<h2 className="m-0" />}>
                    PostHog AI
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Open PostHog AI in the side panel and ask it what this insight shows.
                </Text>
                <div className="flex flex-wrap gap-2">
                    <AIConsentPopoverWrapper onApprove={explain}>
                        <span data-quill>
                            <Button
                                variant="outline"
                                onClick={explain}
                                disabledReason={disabledReason}
                                data-attr="insight-ai-explain-button"
                            >
                                Explain this insight
                            </Button>
                        </span>
                    </AIConsentPopoverWrapper>
                </div>
            </div>
        )
    }

    return (
        <div className="mt-4 mb-4">
            <h2 className="font-semibold text-lg m-0 mb-2 flex items-center gap-2">PostHog AI</h2>
            <p className="text-muted mb-4">Open PostHog AI in the side panel and ask it what this insight shows.</p>
            <div className="flex gap-2 flex-wrap">
                <AIConsentPopoverWrapper onApprove={explain}>
                    <LemonButton
                        type="secondary"
                        onClick={explain}
                        sideIcon={null}
                        data-attr="insight-ai-explain-button"
                        disabledReason={disabledReason}
                    >
                        Explain this insight
                    </LemonButton>
                </AIConsentPopoverWrapper>
            </div>
        </div>
    )
}
