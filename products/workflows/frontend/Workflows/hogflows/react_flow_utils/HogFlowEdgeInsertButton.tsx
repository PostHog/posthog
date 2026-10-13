import clsx from 'clsx'
import { useActions } from 'kea'
import { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { CreateActionType, hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowEditorPanelBuild } from '../panel/HogFlowEditorPanelBuild'
import type { HogFlowEdge } from '../types'

export function HogFlowEdgeInsertButton({
    edge,
    joinEdges,
    x,
    y,
}: {
    edge: HogFlowEdge
    joinEdges?: HogFlowEdge[]
    x: number
    y: number
}): JSX.Element {
    const { setNodeToBeAdded, onDrop } = useActions(hogFlowEditorLogic)
    const [pickerOpen, setPickerOpen] = useState(false)
    const label = joinEdges ? 'Add step after paths join' : 'Add step here'

    const handleInsertAction = (action: CreateActionType): void => {
        setPickerOpen(false)
        setNodeToBeAdded(action)
        onDrop(undefined, edge, joinEdges)
    }

    return (
        <div
            className="nodrag nopan absolute flex size-4 items-center justify-center"
            style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)`, pointerEvents: 'all' }}
        >
            <LemonDropdown
                visible={pickerOpen}
                onVisibilityChange={setPickerOpen}
                closeOnClickInside={false}
                placement="bottom-start"
                overlay={
                    <div className="w-72">
                        <HogFlowEditorPanelBuild className="max-h-96 p-1" onActionSelect={handleInsertAction} />
                    </div>
                }
            >
                <LemonButton
                    htmlType="button"
                    type="tertiary"
                    size="xsmall"
                    sideIcon={null}
                    noPadding
                    tooltip={pickerOpen ? undefined : label}
                    aria-label={label}
                    className="group/insert !size-4 !min-h-0 border-0 !bg-transparent"
                    data-attr={joinEdges ? 'workflow-graph-insert-action-join' : 'workflow-graph-insert-action'}
                >
                    <span
                        className={clsx(
                            'flex size-4 items-center justify-center rounded-full border bg-surface-primary text-secondary transition-colors group-hover/insert:border-accent group-hover/insert:text-accent',
                            pickerOpen && 'border-accent text-accent'
                        )}
                    >
                        <IconPlus className="size-3" />
                    </span>
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
