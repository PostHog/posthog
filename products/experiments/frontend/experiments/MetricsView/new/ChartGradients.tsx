import { ExperimentMetric } from '~/queries/schema/schema-general'

import { useChartColors } from '../shared/colors'
import { getMetricColors } from '../shared/utils'

interface ChartGradientsProps {
    lower?: number
    upper?: number
    gradientId?: string
    metric?: ExperimentMetric
    isSignificant?: boolean
    isBayesian?: boolean
}

/**
 * Shared gradient definitions for experiment charts.
 * This component should be included once in the parent SVG to avoid duplicate definitions.
 */
const NON_SIGNIFICANT_BAYESIAN_OPACITY = 0.5

export function ChartGradients({
    lower = 0,
    upper = 0,
    gradientId = 'chart-gradient',
    metric,
    isSignificant = false,
    isBayesian = false,
}: ChartGradientsProps): JSX.Element {
    const colors = useChartColors()
    const goalColors = getMetricColors(colors, metric?.goal)

    // For non-significant results:
    // - Frequentist: solid gray
    // - Bayesian: use colors but with reduced opacity
    if (!isSignificant) {
        if (!isBayesian) {
            // Frequentist: solid gray
            return (
                <defs>
                    <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="0">
                        <stop offset="100%" stopColor={colors.BAR_DEFAULT} />
                    </linearGradient>
                </defs>
            )
        }
        // Bayesian non-significant: use colors but dimmed
        if (lower < 0 && upper > 0) {
            const zeroOffset = (-lower / (upper - lower)) * 100
            return (
                <defs>
                    <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="0">
                        <stop
                            offset="0%"
                            stopColor={goalColors.negative}
                            stopOpacity={NON_SIGNIFICANT_BAYESIAN_OPACITY}
                        />
                        <stop
                            offset={`${zeroOffset}%`}
                            stopColor={goalColors.negative}
                            stopOpacity={NON_SIGNIFICANT_BAYESIAN_OPACITY}
                        />
                        <stop
                            offset={`${zeroOffset}%`}
                            stopColor={goalColors.positive}
                            stopOpacity={NON_SIGNIFICANT_BAYESIAN_OPACITY}
                        />
                        <stop
                            offset="100%"
                            stopColor={goalColors.positive}
                            stopOpacity={NON_SIGNIFICANT_BAYESIAN_OPACITY}
                        />
                    </linearGradient>
                </defs>
            )
        }
        return (
            <defs>
                <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="0">
                    <stop
                        offset="100%"
                        stopColor={upper <= 0 ? goalColors.negative : goalColors.positive}
                        stopOpacity={NON_SIGNIFICANT_BAYESIAN_OPACITY}
                    />
                </linearGradient>
            </defs>
        )
    }

    if (lower < 0 && upper > 0) {
        const zeroOffset = (-lower / (upper - lower)) * 100
        return (
            <defs>
                <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="0">
                    <stop offset="0%" stopColor={goalColors.negative} />
                    <stop offset={`${zeroOffset}%`} stopColor={goalColors.negative} />
                    <stop offset={`${zeroOffset}%`} stopColor={goalColors.positive} />
                    <stop offset="100%" stopColor={goalColors.positive} />
                </linearGradient>
            </defs>
        )
    }

    return (
        <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="0">
                <stop offset="100%" stopColor={upper <= 0 ? goalColors.negative : goalColors.positive} />
            </linearGradient>
        </defs>
    )
}
