import { BreakdownTileButton } from './BreakdownTileButton'
import { BREAKDOWN_PRESETS } from './errorTrackingBreakdownsSceneLogic'

export function BreakdownPresets(): JSX.Element {
    return (
        <div className="border rounded bg-surface-primary overflow-hidden">
            <div className="text-sm font-semibold p-3 border-b">Presets</div>
            <div>
                {BREAKDOWN_PRESETS.map((item, index) => (
                    <div key={item.property}>
                        <BreakdownTileButton item={item} />
                        {index < BREAKDOWN_PRESETS.length - 1 && <div className="border-b" />}
                    </div>
                ))}
            </div>
        </div>
    )
}
