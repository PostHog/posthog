import clsx from 'clsx'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import { WebPageDirectoryValue } from '~/queries/schema/schema-general'

import { valueChange } from './pageReportsUtils'
import { TrendChange } from './TrendChange'

export interface PageDirectoryMetricCellProps {
    value: WebPageDirectoryValue | undefined
    detail?: React.ReactNode
    tooltip: string
    loading: boolean
}

export function PageDirectoryMetricCell({
    value,
    detail,
    tooltip,
    loading,
}: PageDirectoryMetricCellProps): JSX.Element {
    if (!value) {
        return loading ? <LemonSkeleton className="h-8 w-16 ml-auto" /> : <span className="text-secondary">-</span>
    }
    const current = value.current
    const change = valueChange(value)

    const title = [
        tooltip,
        change === null
            ? null
            : `${change > 0 ? 'Up' : change < 0 ? 'Down' : 'No change'}${change !== 0 ? ` ${percentage(Math.abs(change), 0)}` : ''} from the previous period`,
    ]
        .filter(Boolean)
        .join('. ')

    const changeNode = change !== null && change !== 0 ? <TrendChange change={change} /> : null

    return (
        <Tooltip title={title}>
            <span className="inline-flex flex-col items-end gap-1 leading-tight tabular-nums" translate="no">
                <span className={clsx('font-medium whitespace-nowrap', current === 0 && 'text-secondary font-normal')}>
                    {current.toLocaleString()}
                </span>
                {changeNode || detail ? (
                    <span className="inline-flex items-center gap-1.5 text-xs text-secondary whitespace-nowrap">
                        {changeNode}
                        {detail}
                    </span>
                ) : null}
            </span>
        </Tooltip>
    )
}
