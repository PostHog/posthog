import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'

import { hogFlowEditorLogic } from './hogFlowEditorLogic'
import { getLinearWorkflowActionIds } from './linearWorkflow'
import { StepView } from './steps/components/StepView'
import type { HogFlowAction, HogFlowEdge } from './types'

function HogFlowLinearDropzone({
    active,
    edge,
    draggedActionId,
}: {
    active: boolean
    edge?: HogFlowEdge
    draggedActionId: string | null
}): JSX.Element {
    const { moveNodeToEdge, onDragOver, onDrop } = useActions(hogFlowEditorLogic)
    const [isHighlighted, setIsHighlighted] = useState(false)

    // A step dropped next to where it already is does not move, so that gap is not a target.
    const isNoOpTarget = !!draggedActionId && (edge?.from === draggedActionId || edge?.to === draggedActionId)

    // The gap keeps the same height in both states. A drag that resizes the list under the
    // pointer moves every step away from where the person aimed.
    return (
        <div className="relative my-2 flex h-7 justify-center">
            {!active || !edge || isNoOpTarget ? (
                <div className="absolute inset-y-0 border-l-2 border-primary" aria-hidden="true" />
            ) : (
                <div
                    className={`group absolute inset-x-0 -inset-y-2 flex cursor-pointer items-center justify-center rounded border-2 border-dashed transition-colors ${
                        isHighlighted ? 'border-primary bg-surface-primary' : 'border-primary/50'
                    }`}
                    onDragOver={(event) => {
                        setIsHighlighted(true)
                        onDragOver(event)
                    }}
                    onDragLeave={() => setIsHighlighted(false)}
                    onDrop={(event) => {
                        setIsHighlighted(false)
                        if (draggedActionId) {
                            moveNodeToEdge(draggedActionId, edge, false)
                        } else {
                            onDrop(event, edge)
                        }
                    }}
                    data-attr="workflow-linear-dropzone"
                >
                    <div className="pointer-events-none relative flex size-8 items-center justify-center rounded-full border-2 bg-surface-primary">
                        <IconPlus className="text-lg text-primary" />
                    </div>
                    <span className="pointer-events-none absolute left-[calc(50%+2rem)] whitespace-nowrap rounded border bg-surface-primary px-2 py-1 text-xs text-secondary opacity-0 transition-opacity group-hover:opacity-100 motion-reduce:transition-none">
                        Drop step here
                    </span>
                </div>
            )}
        </div>
    )
}

export function HogFlowLinearEditor(): JSX.Element {
    const { workflow, nodeToBeAdded } = useValues(hogFlowEditorLogic)
    const [draggedActionId, setDraggedActionId] = useState<string | null>(null)
    const actionIds = getLinearWorkflowActionIds(workflow)

    const actionsById = new Map(workflow.actions.map((action) => [action.id, action]))
    const linearActions =
        actionIds?.map((actionId) => actionsById.get(actionId)).filter((action): action is HogFlowAction => !!action) ??
        []

    const edgesBySource = new Map(workflow.edges.map((edge) => [edge.from, edge]))
    const linearEdges = actionIds?.slice(0, -1).map((actionId) => edgesBySource.get(actionId)) ?? []

    return (
        <div className="flex min-h-0 min-w-0 flex-1 overflow-y-auto p-4" data-attr="workflow-linear-editor">
            <div className="mx-auto flex w-full max-w-3xl flex-col">
                {linearActions.map((action, index) => (
                    <div key={action.id} className="flex flex-col">
                        <div
                            draggable={action.type !== 'trigger' && action.type !== 'exit'}
                            onDragStart={(event) => {
                                setDraggedActionId(action.id)
                                event.dataTransfer.effectAllowed = 'move'
                                event.dataTransfer.setData('text/plain', action.id)
                            }}
                            onDragEnd={() => setDraggedActionId(null)}
                            className={`${
                                action.type !== 'trigger' && action.type !== 'exit'
                                    ? 'cursor-grab active:cursor-grabbing'
                                    : ''
                            } ${draggedActionId === action.id ? 'opacity-50' : ''}`}
                            data-attr="workflow-linear-step-drag"
                        >
                            <StepView action={action} layout="list" />
                        </div>
                        {index < linearActions.length - 1 && (
                            <HogFlowLinearDropzone
                                active={!!nodeToBeAdded || !!draggedActionId}
                                edge={linearEdges[index]}
                                draggedActionId={draggedActionId}
                            />
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}
