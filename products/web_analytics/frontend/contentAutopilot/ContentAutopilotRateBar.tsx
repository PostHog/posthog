import { Tooltip } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

export const ContentAutopilotRateBar = ({ rate, tooltip }: { rate: number | null; tooltip?: string }): JSX.Element => {
    if (rate === null) {
        return <span className="block text-right text-muted">-</span>
    }
    const width = Math.max(0, Math.min(100, rate * 100))
    const cell = (
        <span className="flex w-full min-w-24 items-center gap-2">
            <span aria-hidden className="h-2 flex-1 overflow-hidden rounded-full bg-fill-highlight-100">
                <span className="block h-full rounded-full bg-[var(--data-color-1)]" style={{ width: `${width}%` }} />
            </span>
            <span className="w-10 shrink-0 text-right tabular-nums">{percentage(rate, 0)}</span>
        </span>
    )
    return tooltip ? <Tooltip title={tooltip}>{cell}</Tooltip> : cell
}
