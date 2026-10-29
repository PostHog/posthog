import { useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { mcpCustomHarnessesLogic } from '../settings/mcpCustomHarnessesLogic'
import { BrandMark } from './BrandMark'

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
    return (
        <img
            src={icon}
            alt={label ?? ''}
            aria-hidden={label ? undefined : true}
            className={cn('shrink-0 object-contain', className)}
        />
    )
}
