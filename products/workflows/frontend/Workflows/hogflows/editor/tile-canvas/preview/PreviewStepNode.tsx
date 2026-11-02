import { useMemo } from 'react'

import { cn } from 'lib/utils/css-classes'

import { builtInStepKindName } from '../../../builtInSteps'
import type { HogFlowAction } from '../../../types'
import type { StepGraph } from '../stepFacts'
import type { Point } from '../tileCanvasModel'
import { TileCaption } from '../TileCaption'
import { TileFace } from '../TileFace'
import { TileHoverCard } from '../TileHoverCard'
import { tileStep } from '../tileStep'
import { usePreviewCard } from './usePreviewCard'

const NO_TEMPLATES = {}

export function PreviewStepNode({
    action,
    workflow,
    isDarkModeOn,
    expanded,
    at,
    onToggle,
}: {
    action: HogFlowAction
    workflow: StepGraph
    isDarkModeOn: boolean
    expanded: boolean
    at: Point
    onToggle: (actionId: string) => void
}): JSX.Element {
    const tile = useMemo(
        () =>
            tileStep(action, workflow, {
                templatesById: NO_TEMPLATES,
                isDarkModeOn,
                kindName: builtInStepKindName(action),
            }),
        [action, workflow, isDarkModeOn]
    )
    const card = usePreviewCard(expanded)

    return (
        <div
            data-preview-node={action.id}
            className={cn(
                'WorkflowCanvasPreview__node absolute left-0 top-0 flex w-max cursor-pointer items-start gap-3 text-primary',
                card.mounted && 'z-10'
            )}
            style={{ transform: `translate(${at.x}px, ${at.y}px)` }}
            onMouseMove={card.onMouseMove}
            onMouseLeave={card.onMouseLeave}
            onClick={() => onToggle(action.id)}
        >
            <div className="relative">
                <button
                    type="button"
                    className="block rounded-xl"
                    aria-expanded={expanded}
                    aria-label={action.name || tile.label}
                    data-attr="workflow-preview-step"
                >
                    <TileFace tile={tile} count={undefined} />
                </button>
                {card.mounted && (
                    <TileHoverCard
                        open={card.open}
                        action={action}
                        tile={tile}
                        count={undefined}
                        hint={expanded ? 'Click to collapse the step' : 'Click to expand the step'}
                    />
                )}
            </div>
            <TileCaption facts={tile.facts} name={tile.customName} />
        </div>
    )
}
