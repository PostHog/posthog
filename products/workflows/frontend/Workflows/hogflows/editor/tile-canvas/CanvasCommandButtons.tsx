import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { tileCanvasLogic } from './tileCanvasLogic'
import { useCanvasCommands } from './useCanvasCommands'

export function CanvasCommandButtons(): JSX.Element {
    const { panelMode } = useValues(tileCanvasLogic)
    const { togglePanel } = useActions(tileCanvasLogic)
    const { panel, view } = useCanvasCommands()

    return (
        <div className="flex flex-wrap items-center gap-1" data-attr="workflow-tile-commands">
            {panel.map((command) => (
                <LemonButton
                    key={command.id}
                    size="small"
                    icon={command.icon}
                    active={panelMode === command.mode}
                    onClick={() => togglePanel(command.mode)}
                    data-attr={`workflow-tile-command-${command.id}`}
                    tooltip={command.hint ? `${command.label}: ${command.hint}` : command.label}
                >
                    {/* A narrow bar keeps the icons on one row, and the tooltip names each one. */}
                    <span className="@max-[64rem]/workflow-status:sr-only">{command.label}</span>
                </LemonButton>
            ))}
            <LemonMenu
                items={view.map((command) => ({
                    label: command.label,
                    icon: command.icon,
                    onClick: command.run,
                    'data-attr': `workflow-tile-command-${command.id}`,
                }))}
            >
                <LemonButton
                    size="small"
                    icon={<IconEllipsis />}
                    tooltip="More"
                    aria-label="More canvas commands"
                    data-attr="workflow-tile-command-more"
                />
            </LemonMenu>
        </div>
    )
}
