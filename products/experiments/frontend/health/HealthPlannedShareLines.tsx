import { ReferenceLine, useChartLayout } from '@posthog/quill-charts'

import { healthLabelGroups } from './healthChartLabels'
import { formatHealthPercentage } from './healthCheckValues'

// The chart library draws a reference line's label 20px tall, centered on the line.
const PLANNED_LABEL_HEIGHT = 22

export function HealthPlannedShareLines({ planned }: { planned: number[] }): JSX.Element {
    const { scales } = useChartLayout()
    // Highest first, because the y pixel grows down the chart and the groups need ascending pixels.
    const values = [...new Set(planned)].sort((a, b) => b - a)
    const groups = healthLabelGroups(
        values.map((value) => scales.y(value)),
        PLANNED_LABEL_HEIGHT
    )

    const lines = groups.flatMap((group) => {
        const highest = values[group[0]]
        const lowest = values[group[group.length - 1]]
        const label =
            group.length === 1
                ? `Planned ${formatHealthPercentage(highest)}`
                : `Planned ${formatHealthPercentage(lowest)} to ${formatHealthPercentage(highest)}`
        return group.map((index) => ({ value: values[index], label: index === group[0] ? label : undefined }))
    })

    return (
        <>
            {/* The lines without a label come first, because a line drawn later covers the label of a close one. */}
            {[...lines.filter(({ label }) => !label), ...lines.filter(({ label }) => label)].map(({ value, label }) => (
                <ReferenceLine
                    key={value}
                    value={value}
                    label={label}
                    // The goal line's default color is a fixed dark gray, which a dark theme hides.
                    style={{ color: 'var(--color-graph-axis-label)' }}
                    showValueOnHover={false}
                />
            ))}
        </>
    )
}
