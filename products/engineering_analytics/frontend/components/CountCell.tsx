import { compactCount } from '../lib/format'

/** Plain right-aligned count for table cells; comparison belongs in the tiles, never here. */
export function CountCell({ value }: { value: number | null }): JSX.Element {
    return <div className="text-right text-sm font-semibold tabular-nums">{compactCount(value)}</div>
}
