import type { HogFlow, HogFlowAction } from '../../types'
import { StepPreview } from './step-preview/StepPreview'
import { StepCountLine } from './StepCountLine'
import { useTileStep } from './useTileStep'

export function SpotlightCard({
    action,
    workflow,
    count,
    showPreview,
}: {
    action: HogFlowAction
    workflow: HogFlow
    count: number | undefined
    showPreview: boolean
}): JSX.Element {
    const tile = useTileStep(action, workflow)
    return (
        <div
            className="w-65 rounded-xl border bg-surface-primary p-2.5 text-left shadow-lg"
            style={{ borderColor: tile.color }}
        >
            <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: tile.color }}>
                {tile.label}
            </div>
            <div className="ph-no-capture">
                <div className="break-words text-[12.5px] font-semibold leading-snug">{tile.facts.headline}</div>
                {tile.facts.detail && (
                    <div className="break-words text-[11.5px] leading-snug text-secondary">{tile.facts.detail}</div>
                )}
            </div>
            <div
                className="grid transition-[grid-template-rows,opacity] duration-200 motion-reduce:transition-none"
                style={{ gridTemplateRows: showPreview ? '1fr' : '0fr', opacity: showPreview ? 1 : 0 }}
            >
                <div className="min-h-0 overflow-hidden">
                    <div className="mt-2 flex flex-col gap-2 border-t pt-2 text-xs">
                        <StepPreview action={action} tile={tile} />
                        <StepCountLine count={count} />
                    </div>
                </div>
            </div>
        </div>
    )
}
