import { useMemo } from 'react'

import type { HogFlow } from '../../types'
import { MiniFlowEdges } from './MiniFlowEdges'
import { MiniFlowPreview } from './MiniFlowPreview'
import { MiniFlowStep } from './MiniFlowStep'
import { MINI_TILE_SIZE } from './MiniTile'
import { actionsById, layoutMiniFlow } from './tileCanvasModel'
import { useMiniFlowSpotlight } from './useMiniFlowSpotlight'

const SPACING = { tile: MINI_TILE_SIZE, gapX: 30, gapY: 52 }
const BADGE_ROOM = 16

export function MiniFlow({
    workflow,
    memberIds,
    countOf,
    open,
}: {
    workflow: HogFlow
    memberIds: string[]
    countOf: (actionId: string) => number | undefined
    open: boolean
}): JSX.Element {
    const spotlight = useMiniFlowSpotlight(open)
    const layout = useMemo(() => layoutMiniFlow(workflow, memberIds, SPACING), [workflow, memberIds])
    const byId = actionsById(workflow)
    const spotlightNode = layout.nodes.find((node) => node.actionId === spotlight.spotlightId)
    const spotlightAction = spotlightNode && byId.get(spotlightNode.actionId)

    return (
        <div
            className="relative"
            style={{ width: layout.width, height: layout.height + BADGE_ROOM }}
            onMouseMove={spotlight.trackPointer}
            onMouseLeave={spotlight.leaveFlow}
        >
            <MiniFlowEdges layout={layout} opacity={open ? (spotlightNode ? 0.35 : 1) : 0} />
            {layout.nodes.map((node) => {
                const action = byId.get(node.actionId)
                return action ? (
                    <MiniFlowStep
                        key={node.actionId}
                        node={node}
                        action={action}
                        workflow={workflow}
                        count={countOf(action.id)}
                        open={open}
                        dimmed={!!spotlightNode && spotlightNode.actionId !== action.id}
                        highlighted={spotlight.spotlightId === action.id}
                        onEnter={() => spotlight.enterStep(node.actionId)}
                        onLeave={() => spotlight.leaveStep(node.actionId)}
                    />
                ) : null
            })}
            {spotlightNode && spotlightAction && (
                <MiniFlowPreview
                    at={spotlightNode}
                    action={spotlightAction}
                    workflow={workflow}
                    count={countOf(spotlightAction.id)}
                    showPreview={spotlight.showPreview}
                    previewRef={spotlight.previewRef}
                    onEnter={spotlight.enterPreview}
                />
            )}
        </div>
    )
}
