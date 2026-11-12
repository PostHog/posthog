import { useValues } from 'kea'

import { LemonTable } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { VariantTag } from 'scenes/experiments/ExperimentView/VariantTag'
import { getExperimentVariants, getVariantColor } from 'scenes/experiments/utils'

import { type HealthSplitRow, formatHealthPercentage } from './healthCheckValues'

export function HealthExposureSplitTable({ rows, units }: { rows: HealthSplitRow[]; units: string }): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const variants = getExperimentVariants(experiment)
    const hasPlan = rows.some((row) => row.plannedPercentage !== null)

    return (
        <LemonTable
            size="small"
            className="max-w-xl"
            dataSource={rows}
            rowKey="variant"
            data-attr="experiment-health-split"
            columns={[
                {
                    title: 'Variant',
                    key: 'variant',
                    render: (_, row) => <VariantTag variantKey={row.variant} />,
                },
                {
                    title: capitalizeFirstLetter(units),
                    key: 'exposed',
                    align: 'right',
                    render: (_, row) => <span className="tabular-nums">{humanFriendlyNumber(row.exposedCount)}</span>,
                },
                {
                    title: 'Share',
                    key: 'share',
                    render: (_, row) => (
                        <div className="flex items-center gap-2">
                            <div className="w-16 shrink-0">
                                <LemonProgress
                                    percent={row.exposedPercentage}
                                    strokeColor={getVariantColor(row.variant, variants)}
                                />
                            </div>
                            <span className="tabular-nums">{formatHealthPercentage(row.exposedPercentage)}</span>
                        </div>
                    ),
                },
                ...(hasPlan
                    ? [
                          {
                              title: 'Planned',
                              key: 'planned',
                              align: 'right' as const,
                              render: (_: unknown, row: HealthSplitRow) => (
                                  <span className="tabular-nums">
                                      {row.plannedPercentage === null
                                          ? null
                                          : formatHealthPercentage(row.plannedPercentage)}
                                  </span>
                              ),
                          },
                      ]
                    : []),
            ]}
        />
    )
}
