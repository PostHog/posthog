import { BreakdownsTileButton } from './BreakdownsTileButton'
import { BREAKDOWN_PRESETS } from './consts'

export function MiniBreakdowns(): JSX.Element {
    return (
        <div className="border rounded bg-surface-primary overflow-hidden divide-y">
            {BREAKDOWN_PRESETS.map((item) => (
                <BreakdownsTileButton key={item.property} item={item} />
            ))}
        </div>
    )
}
