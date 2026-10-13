import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'

import { getHogFlowBranchColor } from './HogFlowBranchSelection'

/** Labels a path with its color, so a condition reads as the same path in the editor, the list and the graph. */
export function HogFlowBranchTag({
    index,
    label,
    emphasized = false,
}: {
    index: number | null
    label: string
    emphasized?: boolean
}): JSX.Element {
    const color = getHogFlowBranchColor(index)

    return (
        <LemonTag
            size={emphasized ? 'medium' : 'small'}
            className={cn('shrink-0', emphasized && 'uppercase')}
            style={{
                color: emphasized ? `color-mix(in srgb, ${color} 60%, var(--text-3000))` : color,
                borderColor: color,
            }}
        >
            {label}
        </LemonTag>
    )
}
