import type {
    ExperimentMetric,
    ExperimentMetricOutlierHandling as OutlierHandlingConfig,
} from '~/queries/schema/schema-general'
import { isExperimentMeanMetric, isExperimentRatioMetric } from '~/queries/schema/schema-general'

export type MetricOutlierHandlingProps = {
    metric: ExperimentMetric
}

// Percentiles are stored as fractions (0.05, 0.95); display them in percent units.
const toPercent = (fraction: number): number => Math.round(fraction * 100 * 100) / 100

const formatBounds = (config: OutlierHandlingConfig | undefined): string | null => {
    const hasLower = config?.lower_bound_percentile != null
    const hasUpper = config?.upper_bound_percentile != null
    if (!hasLower && !hasUpper) {
        return null
    }
    return [
        hasLower ? `Lower ${toPercent(config!.lower_bound_percentile!)}%` : null,
        hasUpper ? `Upper ${toPercent(config!.upper_bound_percentile!)}%` : null,
    ]
        .filter(Boolean)
        .join(', ')
}

export const MetricOutlierHandling = ({ metric }: MetricOutlierHandlingProps): JSX.Element | null => {
    if (isExperimentMeanMetric(metric)) {
        const bounds = formatBounds({
            lower_bound_percentile: metric.lower_bound_percentile,
            upper_bound_percentile: metric.upper_bound_percentile,
        })
        if (!bounds) {
            return null
        }
        return (
            <div className="text-xs">
                <span className="text-muted">Outlier handling:</span> <span className="font-semibold">{bounds}</span>
            </div>
        )
    }

    if (isExperimentRatioMetric(metric)) {
        const numeratorBounds = formatBounds(metric.numerator_outlier_handling)
        const denominatorBounds = formatBounds(metric.denominator_outlier_handling)
        if (!numeratorBounds && !denominatorBounds) {
            return null
        }
        return (
            <div className="text-xs">
                <span className="text-muted">Outlier handling:</span>{' '}
                <span className="font-semibold">
                    {[
                        numeratorBounds ? `Numerator ${numeratorBounds}` : null,
                        denominatorBounds ? `Denominator ${denominatorBounds}` : null,
                    ]
                        .filter(Boolean)
                        .join(' · ')}
                </span>
            </div>
        )
    }

    return null
}
