import { useValues } from 'kea'

import { AgentPromptButton, type AgentPromptDestination } from 'lib/components/AgentPromptButton'
import { resolveTeamGitHubIntegration } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import type { InstrumentationFix } from '../instrumentationFixes'

export function FixWithAgentButton({
    fix,
    size = 'default',
    dataAttr,
    onRun,
}: {
    fix: InstrumentationFix
    size?: 'default' | 'sm'
    dataAttr: string
    onRun?: () => void
}): JSX.Element | null {
    const { githubIntegrations } = useValues(integrationsLogic)
    // PostHog AI can't edit server code; PostHog Desktop needs a connected repo.
    const excludeAgentKeys: AgentPromptDestination[] = resolveTeamGitHubIntegration(githubIntegrations)
        ? ['posthog-ai']
        : ['posthog-ai', 'posthog-code']
    return (
        <AgentPromptButton
            actions={[{ key: `mcp-analytics-${fix.key}`, label: 'prompt', buildPrompt: () => fix.prompt }]}
            labelMode="destination"
            destinationVerb="Fix in"
            excludeAgentKeys={excludeAgentKeys}
            variant="primary"
            size={size}
            data-attr={dataAttr}
            onRun={onRun}
        />
    )
}
