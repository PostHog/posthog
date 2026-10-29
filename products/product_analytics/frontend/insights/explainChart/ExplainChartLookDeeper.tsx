import { useActions } from 'kea'
import posthog from 'posthog-js'

import { IconSparkles } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

export function ExplainChartLookDeeper({ question }: { question: string }): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    // The leading "!" sends the question to PostHog AI as soon as the panel opens.
    const ask = (): void => openSidePanel(SidePanelTab.Max, `!${question}`)

    return (
        <AIConsentPopoverWrapper onApprove={ask}>
            <Button
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => {
                    posthog.capture('explain chart look deeper clicked')
                    ask()
                }}
                data-attr="explain-chart-look-deeper"
            >
                <IconSparkles />
                Look deeper with PostHog AI
            </Button>
        </AIConsentPopoverWrapper>
    )
}
