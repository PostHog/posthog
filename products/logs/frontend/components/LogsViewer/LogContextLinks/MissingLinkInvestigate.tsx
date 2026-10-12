import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconSearch, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AgentPromptButton, AgentPromptDestination } from 'lib/components/AgentPromptButton/AgentPromptButton'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { humanList } from 'lib/utils/strings'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { SidePanelTab } from '~/types'

import { getServiceName } from 'products/logs/frontend/components/LogsViewer/LogContextSelector/logContextUtils'
import { ParsedLogMessage } from 'products/logs/frontend/types'

import type { LogContextLinksSurface } from './LogContextLinks'
import { MissingLink, buildMissingLinkPrompt } from './missingLinkPrompt'

type InvestigateOption = AgentPromptDestination | 'posthog-ai-task'

// pinned: analytics event names and properties, renaming breaks dashboards
function captureInvestigate(
    event: 'shown' | 'clicked',
    log: ParsedLogMessage,
    missing: MissingLink[],
    surface: LogContextLinksSurface,
    option?: InvestigateOption
): void {
    posthog.capture(`logs missing link investigate ${event}`, {
        option,
        missing,
        source: `log-${surface}`,
        service_name: getServiceName(log),
    })
}

function missingLabel(missing: MissingLink[]): string {
    const links = humanList(missing)
    return `${links.charAt(0).toUpperCase()}${links.slice(1)} ${missing.length > 1 ? 'links' : 'link'} missing. Find out why:`
}

export function MissingLinkInvestigate({
    log,
    missing,
    surface,
}: {
    log: ParsedLogMessage
    missing: MissingLink[]
    surface: LogContextLinksSurface
}): JSX.Element {
    const { isMaxAvailable, effectivePhaiView } = useValues(maxGlobalLogic)
    const { todayRailEnabled } = useValues(todayShellLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    // Only the new PostHog AI side panel turns a run prompt into a task; the legacy view would start a chat.
    const canStartTask = isMaxAvailable && effectivePhaiView === 'new' && !todayRailEnabled

    useOnMountEffect(() => captureInvestigate('shown', log, missing, surface))

    return (
        <div className="flex flex-wrap items-center gap-1">
            <span className="flex items-center gap-1 text-xs text-secondary">
                <IconSearch />
                <span>{missingLabel(missing)}</span>
            </span>
            <AgentPromptButton
                storageKey="logs-missing-link"
                defaultAgentKey="clipboard"
                agentKeys={['clipboard', 'claude-code', 'cursor', 'codex', 'posthog-code']}
                size="xs"
                actions={[
                    {
                        key: 'investigate',
                        label: 'prompt',
                        buildPrompt: () => buildMissingLinkPrompt(log, missing),
                    },
                ]}
                onRun={({ agentKey }) =>
                    captureInvestigate('clicked', log, missing, surface, agentKey as AgentPromptDestination)
                }
                data-attr={`logs-${surface}-missing-link-agent-prompt`}
            />
            {canStartTask && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconSparkles />}
                    onClick={() => {
                        captureInvestigate('clicked', log, missing, surface, 'posthog-ai-task')
                        // A leading "!" makes the side panel start the task, behind the AI data consent gate.
                        openSidePanel(SidePanelTab.Max, `!${buildMissingLinkPrompt(log, missing)}`)
                    }}
                    data-attr={`logs-${surface}-missing-link-posthog-ai`}
                >
                    Ask PostHog AI
                </LemonButton>
            )}
        </div>
    )
}
