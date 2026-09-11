import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'

export function DiscussReportButton({ report, reportUrl }: { report: SignalReport; reportUrl: string }): JSX.Element {
    const { isDiscussing, isCreatingPr, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { openReportDiscussion } = useActions(inboxTaskKickoffLogic)

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconSparkles />}
            loading={isDiscussing}
            disabledReason={aiConsentDisabledReason ?? (isCreatingPr ? 'An implementation is starting.' : undefined)}
            onClick={() => openReportDiscussion(report, reportUrl)}
            tooltip="Ask PostHog AI about this report in the sidebar"
        >
            Ask AI
        </LemonButton>
    )
}
