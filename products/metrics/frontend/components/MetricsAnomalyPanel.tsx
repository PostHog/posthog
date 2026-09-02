import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDivider, LemonDropdown, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MetricTopMoverRow } from '../metricsAnomaly'
import { type MetricsAnomalyBadge, metricsViewerLogic } from './metricsViewerLogic'

const MoverRow = ({ mover, onClick }: { mover: MetricTopMoverRow; onClick: () => void }): JSX.Element => (
    <LemonButton fullWidth size="small" onClick={onClick} data-attr="metrics-anomaly-mover">
        <div className="flex items-center justify-between gap-2 w-full min-w-0">
            <span className="truncate font-mono text-xs">
                {mover.key}={mover.label}
            </span>
            <span className="shrink-0 text-xs text-secondary">
                {mover.isNew ? (
                    <LemonTag type="warning">New</LemonTag>
                ) : (
                    <>
                        {humanFriendlyNumber(mover.baselineValue)} → {humanFriendlyNumber(mover.anomalyValue)}{' '}
                        <span className={mover.direction === 'up' ? 'text-danger' : 'text-success'}>
                            {mover.direction === 'up' ? '▲' : '▼'} {mover.percent}%
                        </span>
                    </>
                )}
            </span>
        </div>
    </LemonButton>
)

/**
 * The "what changed" panel behind the anomaly badge.
 *
 * The backend already attributes a metric's move to the label values that drove it
 * (`anomaly.py`); this puts that ranking in front of the user, and lets one click narrow the
 * chart to a finding so an investigation can stack.
 */
export function MetricsAnomalyPanel({ anomaly }: { anomaly: MetricsAnomalyBadge }): JSX.Element {
    const { anomalyTopMovers } = useValues(metricsViewerLogic)
    const { addAttributeFilter } = useActions(metricsViewerLogic)
    const [isOpen, setIsOpen] = useState(false)

    return (
        <LemonDropdown
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            placement="bottom-start"
            overlay={
                <div className="w-80 max-w-full p-1">
                    <div className="px-2 py-1 text-xs text-secondary">
                        Baseline {humanFriendlyNumber(anomaly.baselineMean)} → recent{' '}
                        {humanFriendlyNumber(anomaly.anomalyMean)}
                        {anomaly.onsetTime ? `, from ${dayjs(anomaly.onsetTime).format('D MMM HH:mm')}` : ''}
                    </div>
                    <LemonDivider className="my-1" />
                    {anomalyTopMovers.length ? (
                        <>
                            <div className="px-2 py-1 text-xs font-semibold">Biggest movers</div>
                            {anomalyTopMovers.map((mover) => (
                                <MoverRow
                                    key={`${mover.key}:${mover.label}`}
                                    mover={mover}
                                    onClick={() => {
                                        addAttributeFilter(mover.key, mover.label)
                                        setIsOpen(false)
                                    }}
                                />
                            ))}
                            <div className="px-2 py-1 text-xs text-secondary">Pick one to filter the chart to it.</div>
                        </>
                    ) : (
                        <div className="px-2 py-1 text-xs text-secondary">
                            No single label stands out, so the change looks spread across the metric. Group by an
                            attribute to break it down.
                        </div>
                    )}
                </div>
            }
        >
            <LemonTag
                type="warning"
                onClick={() => setIsOpen(!isOpen)}
                className="cursor-pointer"
                data-attr="metrics-viewer-anomaly-badge"
            >
                {anomaly.direction === 'up' ? '▲' : '▼'} {anomaly.percent}% vs baseline
            </LemonTag>
        </LemonDropdown>
    )
}
