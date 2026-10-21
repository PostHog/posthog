import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { HogFlowStepNameFields } from '../../panel/HogFlowStepNameFields'
import type { HogFlowAction } from '../../types'
import { tileCanvasLogic } from './tileCanvasLogic'
import { TileCaption } from './TileCaption'
import { TileFace } from './TileFace'
import { useTileStep } from './useTileStep'

const KIND_BORDER_WIDTH = 3

export function TileStepPanelHead({ action }: { action: HogFlowAction }): JSX.Element {
    const { workflow, countOf, selectedNode, selectedNodeCanBeDeleted } = useValues(tileCanvasLogic)
    const { onNodesDelete, closePanel } = useActions(tileCanvasLogic)
    const tile = useTileStep(action, workflow)
    return (
        <div
            className="relative z-10 flex shrink-0 flex-col gap-3 border-b bg-surface-primary px-3 pb-3 pt-3"
            style={{ borderTop: `${KIND_BORDER_WIDTH}px solid ${tile.color}` }}
            data-attr="workflow-tile-panel-head"
        >
            <div className="relative flex items-start gap-3">
                <TileFace tile={tile} count={countOf(action.id)} />
                <TileCaption facts={tile.facts} />
                <div
                    className="absolute right-0 top-0 text-[10px] font-semibold uppercase tracking-wider"
                    style={{ color: tile.color }}
                >
                    {tile.label}
                </div>
            </div>
            <div className="flex items-start gap-2">
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <HogFlowStepNameFields action={action} />
                </div>
                {selectedNode?.deletable && (
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Delete this step"
                        onClick={() => {
                            onNodesDelete([selectedNode])
                            closePanel()
                        }}
                        disabledReason={selectedNodeCanBeDeleted ? undefined : 'Clean up branching steps first'}
                    />
                )}
            </div>
        </div>
    )
}
