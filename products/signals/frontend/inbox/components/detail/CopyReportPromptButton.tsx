import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonMenuOverlay } from '@posthog/lemon-ui'

import type { AgentPromptDestination } from 'lib/components/AgentPromptButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { captureInboxReportAction } from '../../inboxAnalytics'
import type { SignalReport } from '../../types'
import { buildReportImplementationPrompt } from './buildReportImplementationPrompt'
import { IMPLEMENTATION_AGENTS } from './implementationAgents'

export function CopyReportPromptButton({
    report,
    reportUrl,
    prUrl,
}: {
    report: SignalReport
    reportUrl: string
    prUrl: string
}): JSX.Element {
    const runPrompt = (agent: AgentPromptDestination, run: (prompt: string) => void): void => {
        captureInboxReportAction({
            report,
            actionType: 'copy_implementation_prompt',
            surface: 'detail_pane',
            extra: { agent },
        })
        run(buildReportImplementationPrompt(report, reportUrl, prUrl))
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconCopy />}
            onClick={() => runPrompt('clipboard', (prompt) => void copyToClipboard(prompt, 'prompt for your agent'))}
            data-attr="inbox-report-copy-prompt"
            sideAction={{
                tooltip: 'Open prompt in an agent',
                'aria-label': 'Open prompt in an agent',
                dropdown: {
                    placement: 'bottom-end',
                    overlay: (
                        <LemonMenuOverlay
                            items={IMPLEMENTATION_AGENTS.map((agent) => ({
                                key: agent.key,
                                label: agent.name,
                                icon: agent.icon,
                                onClick: () => runPrompt(agent.key, agent.open),
                            }))}
                        />
                    ),
                },
            }}
        >
            Copy Prompt
        </LemonButton>
    )
}
