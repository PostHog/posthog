import { compactCount } from '../lib/format'

export function CountCell({ value }: { value: number | null }): JSX.Element {
    return <div className="text-right text-sm font-semibold tabular-nums">{compactCount(value)}</div>
}
