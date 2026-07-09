import { getColorVar } from 'lib/colors'
import { type SparklineTimeSeries } from 'lib/components/Sparkline'

/** Legend for the multi-series chart — a colour swatch + name per series. Hidden for a single series. */
export function MetricsChartLegend({ series }: { series: SparklineTimeSeries[] }): JSX.Element | null {
    if (series.length < 2) {
        return null
    }
    return (
        <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
            {series.map((s, i) => (
                <span key={`${i}-${s.name}`} className="flex items-center gap-1.5 text-xs text-secondary">
                    <span
                        className="w-2 h-2 rounded-full shrink-0"
                        // Dynamic per-series colour can't be a Tailwind class.
                        style={{ backgroundColor: getColorVar(s.color ?? 'muted') }}
                    />
                    {s.name}
                </span>
            ))}
        </div>
    )
}
