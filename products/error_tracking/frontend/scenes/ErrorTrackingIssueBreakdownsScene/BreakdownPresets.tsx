import { BreakdownTileButton } from './BreakdownTileButton'
import { BREAKDOWN_PRESETS } from './errorTrackingBreakdownsSceneLogic'

export function BreakdownPresets(): JSX.Element {
    return (
        <div className="border rounded bg-surface-primary overflow-hidden">
            <div className="text-sm font-semibold p-3 border-b">Presets</div>
            <div className="divide-y">
                {BREAKDOWN_PRESETS.map((item) => (
                    <div key={item.property}>
                        <BreakdownTileButton item={item} />
                    </div>
                ))}
            </div>
        </div>
    )
}
