import { useValues } from 'kea'

import { mcpCustomHarnessesLogic } from '../settings/mcpCustomHarnessesLogic'
import { BrandMark } from './BrandMark'
import { HarnessIconMask } from './HarnessIconMask'

/** The icon a team set for one of its custom harnesses, or the generic harness mark when it set none. */
export function CustomHarnessIcon({
    harness,
    label,
    className = 'size-4',
}: {
    harness: string
    label?: string
    className?: string
}): JSX.Element {
    const { customHarnessIcons } = useValues(mcpCustomHarnessesLogic)
    const icon = customHarnessIcons.get(harness)
    if (!icon) {
        return <BrandMark name="Other harnesses" label={label} className={className} />
    }
    return <HarnessIconMask src={icon} label={label} className={className} />
}
