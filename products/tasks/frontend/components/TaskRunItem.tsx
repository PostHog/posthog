import { dayjs } from 'lib/dayjs'

import { formatTimeAgo } from '../lib/util-functions'
import { TaskRun } from '../types'
import { TaskRunStatusBadge } from './TaskRunStatusBadge'

export interface TaskRunItemProps {
    run: TaskRun
    isSelected: boolean
    onClick: () => void
}

export function TaskRunItem({ run, isSelected, onClick }: TaskRunItemProps): JSX.Element {
    const date = dayjs(run.created_at)
    const timeAgo = formatTimeAgo(run.created_at)

    return (
        <button
            type="button"
            onClick={onClick}
            aria-label={`View run from ${date.format('MMM D, YYYY HH:mm')}`}
            className={`w-full text-left px-3 py-2 rounded hover:bg-bg-light transition-colors ${
                isSelected ? 'bg-primary-highlight border border-primary' : 'border border-transparent'
            }`}
        >
            <div className="flex items-center justify-between gap-2 mb-1">
                <TaskRunStatusBadge run={run} />
                <span className="text-xs text-muted">{timeAgo}</span>
            </div>
            <div className="text-xs text-muted">{date.format('MMM D, YYYY HH:mm')}</div>
            {run.branch && <div className="text-xs text-muted mt-1 font-mono truncate">{run.branch}</div>}
        </button>
    )
}
