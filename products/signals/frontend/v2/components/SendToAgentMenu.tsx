import { LemonMenu, lemonToast } from '@posthog/lemon-ui'

export const DEMO_CODING_AGENTS = [
    { name: 'Cursor', where: 'opens in app' },
    { name: 'Claude Code', where: 'runs in terminal' },
    { name: 'Codex CLI', where: 'runs in terminal' },
]

export interface SendToAgentMenuProps {
    /** The trigger element, e.g. a LemonButton */
    children: JSX.Element
    /** Prompt copied by the "Copy the prompt instead" item */
    promptText: string
    onSelectAgent: (agentName: string) => void
    visible?: boolean
    onVisibilityChange?: (visible: boolean) => void
    placement?: 'bottom-start' | 'top-end'
}

/**
 * "Send to my agent" menu for the demo pages: hand an report off to an
 * external coding agent with full context, or copy an equivalent prompt.
 */
export function SendToAgentMenu({
    children,
    promptText,
    onSelectAgent,
    visible,
    onVisibilityChange,
    placement = 'bottom-start',
}: SendToAgentMenuProps): JSX.Element {
    return (
        <LemonMenu
            visible={visible}
            onVisibilityChange={onVisibilityChange}
            placement={placement}
            items={[
                {
                    title: 'Hand off with full context',
                    items: DEMO_CODING_AGENTS.map((agent) => ({
                        label: (
                            <span className="flex w-full items-baseline gap-3">
                                <span className="flex-1">{agent.name}</span>
                                <span className="text-xs text-tertiary">{agent.where}</span>
                            </span>
                        ),
                        onClick: () => onSelectAgent(agent.name),
                        'data-attr': `v2-send-to-${agent.name.toLowerCase().replace(/\s+/g, '-')}`,
                    })),
                },
                {
                    items: [
                        {
                            label: (
                                <span className="flex w-full items-baseline gap-3">
                                    <span className="flex-1">Copy the prompt instead</span>
                                    <span className="text-xs text-tertiary">needs PostHog MCP or CLI</span>
                                </span>
                            ),
                            onClick: () => {
                                navigator.clipboard?.writeText(promptText).catch(() => {})
                                lemonToast.success('Prompt copied to clipboard')
                            },
                            'data-attr': 'v2-copy-agent-prompt',
                        },
                    ],
                },
            ]}
        >
            {children}
        </LemonMenu>
    )
}
