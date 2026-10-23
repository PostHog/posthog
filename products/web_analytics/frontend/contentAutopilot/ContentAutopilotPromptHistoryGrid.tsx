import clsx from 'clsx'

import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { PromptHistoryCell, PromptHistoryCellStatus, PromptHistoryGrid, engineLabel } from './utils'

const STATUS_LABELS: Record<PromptHistoryCellStatus, string> = {
    cited: 'Cited',
    not_cited: 'Not cited',
    failed: 'Failed',
    no_run: 'No run',
}

const STATUS_CLASSES: Record<PromptHistoryCellStatus, string> = {
    cited: 'bg-success',
    not_cited: 'bg-warning',
    failed: 'bg-danger',
    no_run: 'bg-border',
}

const cellTooltip = ({ date, status, checks, cited, failed }: PromptHistoryCell): string => {
    const day = dayjs(date).format('MMM D, YYYY')
    if (status === 'no_run') {
        return `${day}: no run`
    }
    const answered = checks - failed
    const failures = failed ? `, ${failed} failed` : ''
    return `${day}: ${STATUS_LABELS[status].toLowerCase()} (cited in ${cited} of ${answered} answers${failures})`
}

export const ContentAutopilotPromptHistoryGrid = ({ grid }: { grid: PromptHistoryGrid }): JSX.Element => (
    <div className="flex flex-col gap-2">
        <div className="overflow-x-auto">
            <div className="flex flex-col gap-1 w-max">
                {grid.rows.map(({ engine, cells }) => (
                    <div key={engine} className="flex items-center gap-2">
                        <span className="w-20 shrink-0 text-xs text-muted truncate">{engineLabel(engine)}</span>
                        <div className="flex gap-0.5">
                            {cells.map((cell) => (
                                <Tooltip key={cell.date} title={cellTooltip(cell)}>
                                    <span
                                        role="img"
                                        aria-label={cellTooltip(cell)}
                                        className={clsx('block size-4 rounded-sm', STATUS_CLASSES[cell.status])}
                                    />
                                </Tooltip>
                            ))}
                        </div>
                    </div>
                ))}
                {grid.dates.length > 0 ? (
                    <div className="flex justify-between pl-22 text-xs text-muted">
                        <span>{dayjs(grid.dates[0]).format('MMM D')}</span>
                        <span>{dayjs(grid.dates[grid.dates.length - 1]).format('MMM D')}</span>
                    </div>
                ) : null}
            </div>
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-muted">
            {(Object.keys(STATUS_LABELS) as PromptHistoryCellStatus[]).map((status) => (
                <span key={status} className="flex items-center gap-1">
                    <span className={clsx('block size-3 rounded-sm', STATUS_CLASSES[status])} />
                    {STATUS_LABELS[status]}
                </span>
            ))}
        </div>
    </div>
)
