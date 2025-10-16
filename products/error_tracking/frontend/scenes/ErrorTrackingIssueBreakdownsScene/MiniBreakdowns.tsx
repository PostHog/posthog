import { BreakdownTileButton } from './BreakdownTileButton'
import { BREAKDOWN_PRESETS } from './errorTrackingBreakdownsLogic'

export function MiniBreakdowns(): JSX.Element {
    return (
        <div className="border rounded bg-surface-primary overflow-hidden divide-y">
            {BREAKDOWN_PRESETS.map((item) => (
                <div key={item.property}>
                    <BreakdownTileButton item={item} />
                </div>
            ))}
        </div>
    )
}
