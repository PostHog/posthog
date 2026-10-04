import { IconLogomark } from '@posthog/icons'

import {
    buildClaudeCodeDeepLink,
    buildCodexDeepLink,
    buildCursorDeepLink,
    buildPostHogCodeDeepLink,
} from 'lib/components/AgentPromptButton'
import type { AgentPromptDestination } from 'lib/components/AgentPromptButton'
import { AgentLogo, claudeLogo, cursorLogo, openaiLogo } from 'lib/components/AgentPromptButton/AgentLogo'

export interface ImplementationAgent {
    key: AgentPromptDestination
    name: string
    icon: JSX.Element
    buildDeepLink: (prompt: string) => string
}

export const IMPLEMENTATION_AGENTS: ImplementationAgent[] = [
    {
        key: 'posthog-code',
        name: 'PostHog Desktop',
        icon: <IconLogomark />,
        buildDeepLink: buildPostHogCodeDeepLink,
    },
    {
        key: 'claude-code',
        name: 'Claude Code',
        icon: <AgentLogo logo={claudeLogo} />,
        buildDeepLink: buildClaudeCodeDeepLink,
    },
    {
        key: 'cursor',
        name: 'Cursor',
        icon: <AgentLogo logo={cursorLogo} logoClassName="dark:invert" />,
        buildDeepLink: buildCursorDeepLink,
    },
    {
        key: 'codex',
        name: 'Codex',
        icon: <AgentLogo logo={openaiLogo} />,
        buildDeepLink: buildCodexDeepLink,
    },
]
