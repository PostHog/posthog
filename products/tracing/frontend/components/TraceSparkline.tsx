import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'

import { MOCK_SPARKLINE_DATA } from '../data/mockTraceData'

export function TraceSparkline(): JSX.Element {
    const series: SparklineTimeSeries[] = MOCK_SPARKLINE_DATA.series.map((s) => ({
        name: s.name,
        values: s.values,
        color: s.color,
    }))

    return (
        <div className="h-20">
            <Sparkline data={series} labels={MOCK_SPARKLINE_DATA.labels} type="bar" />
        </div>
    )
}
