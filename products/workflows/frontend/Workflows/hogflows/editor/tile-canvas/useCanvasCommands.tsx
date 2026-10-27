import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import {
    IconBrackets,
    IconClock,
    IconCollapse,
    IconExpand,
    IconGraph,
    IconList,
    IconPlay,
    IconPlusSquare,
    IconScreen,
} from '@posthog/icons'

import { tileCanvasLogic, TileCanvasPanelMode } from './tileCanvasLogic'
import type { PaletteCommand } from './tileCanvasModel'

export interface CanvasCommand extends PaletteCommand {
    icon: JSX.Element
    run: () => void
}

export interface PanelCommand extends CanvasCommand {
    mode: TileCanvasPanelMode
}

export interface CanvasCommands {
    panel: PanelCommand[]
    view: CanvasCommand[]
}

type PanelDefinition = Omit<PanelCommand, 'run'> & { needsSavedWorkflow?: boolean }

const PANELS: PanelDefinition[] = [
    {
        id: 'build',
        mode: 'build',
        label: 'Build',
        hint: 'Browse every step you can add',
        icon: <IconPlusSquare />,
    },
    {
        id: 'test',
        mode: 'test',
        label: 'Test',
        hint: 'Run the workflow for one person',
        icon: <IconPlay />,
        needsSavedWorkflow: true,
    },
    {
        id: 'logs',
        mode: 'logs',
        label: 'Logs',
        hint: 'Recent runs, newest first',
        icon: <IconList />,
        needsSavedWorkflow: true,
    },
    {
        id: 'variables',
        mode: 'variables',
        label: 'Variables',
        hint: 'Values the steps can read and write',
        icon: <IconBrackets />,
    },
    {
        id: 'metrics',
        mode: 'metrics',
        label: 'Metrics',
        hint: 'How many people each step reached',
        icon: <IconGraph />,
        needsSavedWorkflow: true,
    },
    {
        id: 'history',
        mode: 'history',
        label: 'History',
        hint: 'See and restore previous versions',
        icon: <IconClock />,
        needsSavedWorkflow: true,
    },
]

function tracked<Command extends CanvasCommand>(command: Command): Command {
    return {
        ...command,
        run: () => {
            posthog.capture('workflows tile canvas command run', { command: command.id })
            command.run()
        },
    }
}

export function useCanvasCommands(): CanvasCommands {
    const { pathGroups, allPathsCollapsed, isSavedWorkflow } = useValues(tileCanvasLogic)
    const { openPanel, toggleAllPaths, requestFit } = useActions(tileCanvasLogic)
    const hasPaths = pathGroups.length > 0

    return useMemo((): CanvasCommands => {
        const available = (panels: PanelDefinition[]): PanelCommand[] =>
            panels
                .filter((panel) => isSavedWorkflow || !panel.needsSavedWorkflow)
                .map(({ needsSavedWorkflow: _, ...panel }) => tracked({ ...panel, run: () => openPanel(panel.mode) }))
        const pathsCommand: CanvasCommand = {
            id: 'paths',
            label: allPathsCollapsed ? 'Open all paths' : 'Collapse all paths',
            icon: allPathsCollapsed ? <IconExpand /> : <IconCollapse />,
            run: toggleAllPaths,
        }
        const fitCommand: CanvasCommand = {
            id: 'fit',
            label: 'Fit to screen',
            hint: 'Show the whole workflow',
            icon: <IconScreen />,
            run: requestFit,
        }
        return {
            panel: available(PANELS),
            view: [...(hasPaths ? [pathsCommand] : []), fitCommand].map(tracked),
        }
    }, [openPanel, isSavedWorkflow, hasPaths, allPathsCollapsed, toggleAllPaths, requestFit])
}
