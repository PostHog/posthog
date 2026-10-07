import { IconLogomark } from '@posthog/icons'

import {
    buildClaudeCodeDeepLink,
    buildClaudeCodeVSCodeDeepLink,
    buildClaudeCodeWebLink,
    buildClaudeDesktopDeepLink,
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
    open: (prompt: string) => void
}

function openDeepLink(buildDeepLink: (prompt: string) => string): (prompt: string) => void {
    return (prompt) => window.open(buildDeepLink(prompt), '_blank')
}

export const IMPLEMENTATION_AGENTS: ImplementationAgent[] = [
    {
        key: 'posthog-code',
        name: 'PostHog Desktop',
        icon: <IconLogomark />,
        open: openDeepLink(buildPostHogCodeDeepLink),
    },
    {
        key: 'claude-code',
        name: 'Claude Code CLI',
        icon: <AgentLogo logo={claudeLogo} />,
        open: openDeepLink(buildClaudeCodeDeepLink),
    },
    {
        key: 'claude-desktop',
        name: 'Claude Desktop',
        icon: <AgentLogo logo={claudeLogo} />,
        open: openDeepLink(buildClaudeDesktopDeepLink),
    },
    {
        key: 'claude-code-vscode',
        name: 'Claude Code in VS Code',
        icon: <AgentLogo logo={claudeLogo} />,
        open: openDeepLink(buildClaudeCodeVSCodeDeepLink),
    },
    {
        key: 'claude-code-web',
        name: 'Claude Code on the web',
        icon: <AgentLogo logo={claudeLogo} />,
        open: (prompt) => window.open(buildClaudeCodeWebLink(prompt), '_blank', 'noopener,noreferrer'),
    },
    {
        key: 'cursor',
        name: 'Cursor',
        icon: <AgentLogo logo={cursorLogo} logoClassName="dark:invert" />,
        open: openDeepLink(buildCursorDeepLink),
    },
    {
        key: 'codex',
        name: 'Codex',
        icon: <AgentLogo logo={openaiLogo} />,
        open: openDeepLink(buildCodexDeepLink),
    },
]
