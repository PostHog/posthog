import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { aiShellLogic } from '~/layout/ai/aiShellLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

export function InvestigationAssistantButton(): JSX.Element | null {
    const { isMaxAvailable, isPhaiSandboxFlagOn } = useValues(aiShellLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const ask = (): void =>
        openSidePanel(
            SidePanelTab.Max,
            'Help investigate the question in this notebook. Start by reviewing the premise checks and existing evidence, then propose the next query that would distinguish competing explanations.'
        )

    if (!isMaxAvailable || isPhaiSandboxFlagOn) {
        return null
    }

    return (
        <AIConsentPopoverWrapper onApprove={ask}>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconSparkles />}
                onClick={ask}
                data-attr="investigation-ask-ai"
            >
                Ask PostHog AI
            </LemonButton>
        </AIConsentPopoverWrapper>
    )
}
