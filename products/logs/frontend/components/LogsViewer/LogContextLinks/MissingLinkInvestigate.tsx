import { useActions, useValues } from 'kea'

import { IconSearch, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AgentPromptButton, AgentPromptDestination } from 'lib/components/AgentPromptButton/AgentPromptButton'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { humanList } from 'lib/utils/strings'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'

import { ParsedLogMessage } from 'products/logs/frontend/types'

import type { LogContextLinksSurface } from './LogContextLinks'
import { missingLinkInvestigateLogic } from './missingLinkInvestigateLogic'
import { MissingLink, buildMissingLinkPrompt } from './missingLinkPrompt'
import { captureInvestigate, missingLinkEventContext } from './missingLinkTelemetry'

function missingLabel(missing: MissingLink[]): string {
    const links = humanList(missing)
    return `${links.charAt(0).toUpperCase()}${links.slice(1)} ${missing.length > 1 ? 'links' : 'link'} missing. Find out why:`
}

export function MissingLinkInvestigate({
    log,
    missing,
    surface,
    onLeave,
}: {
    log: ParsedLogMessage
    missing: MissingLink[]
    surface: LogContextLinksSurface
    onLeave?: () => void
}): JSX.Element {
    const { isMaxAvailable } = useValues(maxGlobalLogic)
    const { launching, startsSidePanelTask } = useValues(missingLinkInvestigateLogic)
    const { startTask } = useActions(missingLinkInvestigateLogic)

    const eventContext = missingLinkEventContext(log, missing, surface)

    useOnMountEffect(() => captureInvestigate('shown', eventContext))

    return (
        <div className="flex flex-wrap items-center gap-1">
            <span className="flex items-center gap-1 text-xs text-secondary">
                <IconSearch />
                <span>{missingLabel(missing)}</span>
            </span>
            <AgentPromptButton
                size="xs"
                actions={[
                    {
                        key: 'investigate',
                        label: 'prompt',
                        buildPrompt: () => buildMissingLinkPrompt(log, missing),
                    },
                ]}
                onRun={({ agentKey }) =>
                    captureInvestigate('clicked', eventContext, { option: agentKey as AgentPromptDestination })
                }
                data-attr={`logs-${surface}-missing-link-agent-prompt`}
            />
            {isMaxAvailable && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconSparkles />}
                    loading={startsSidePanelTask && launching}
                    onClick={() => startTask(buildMissingLinkPrompt(log, missing), onLeave ?? (() => {}), eventContext)}
                    data-attr={`logs-${surface}-missing-link-posthog-ai`}
                >
                    Ask PostHog AI
                </LemonButton>
            )}
        </div>
    )
}
