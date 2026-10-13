import './MetricsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored series. Latency is spiky around a steady band; memory is a
// sawtooth that climbs and drops on every garbage-collection cycle.
const LINE_LATENCY = 'M 0 24 L 10 20 L 20 26 L 30 18 L 40 25 L 50 12 L 60 22 L 70 16 L 80 24 L 90 19 L 100 21'
const LINE_MEMORY = 'M 0 30 L 14 22 L 28 14 L 29 30 L 43 23 L 57 15 L 58 31 L 72 24 L 86 16 L 87 30 L 100 24'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the metrics empty state: a metric list driving a
 * chart card. Clicking the memory gauge swaps the chart from request latency to
 * the memory sawtooth. One hidden checkbox drives it via `:checked ~` styles -
 * no timers or state, per the preview rules in the `building-product-empty-states`
 * skill. Chart states crossfade in `__swap` grids, so nothing shifts.
 */
export function MetricsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('MetricsPreview', isStatic && 'MetricsPreview--static')}>
            {/* Selection state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="metrics-preview-select" className="MetricsPreview__checkbox" />

            <div className="MetricsPreview__panel">
                <div className="MetricsPreview__head">
                    <span className="MetricsPreview__title">
                        <span className="MetricsPreview__live-dot" aria-hidden="true" />
                        Metrics
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="MetricsPreview__rows">
                    <div className="MetricsPreview__row MetricsPreview__row--latency">
                        <span className="MetricsPreview__radio" aria-hidden="true" />
                        <span className="MetricsPreview__name">http_request_duration_seconds</span>
                        <span className="MetricsPreview__kind">histogram</span>
                    </div>
                    <label htmlFor="metrics-preview-select" className="MetricsPreview__row MetricsPreview__row--memory">
                        <span className="MetricsPreview__radio" aria-hidden="true" />
                        <span className="MetricsPreview__name">process_resident_memory_bytes</span>
                        <span className="MetricsPreview__kind">gauge</span>
                    </label>
                    <div className="MetricsPreview__row">
                        <span className="MetricsPreview__radio MetricsPreview__radio--off" aria-hidden="true" />
                        <span className="MetricsPreview__name">orders_total</span>
                        <span className="MetricsPreview__kind">counter</span>
                    </div>
                </div>
                <div className="MetricsPreview__hint MetricsPreview__swap">
                    <span className="MetricsPreview__when-latency">Click the memory gauge to chart it instead.</span>
                    <span className="MetricsPreview__when-memory">
                        A sawtooth: memory climbs, then GC drops it. Click again for latency.
                    </span>
                </div>
            </div>

            <div className="MetricsPreview__chart">
                <div className="MetricsPreview__spark-head">
                    <span className="MetricsPreview__spark-title MetricsPreview__swap">
                        <span className="MetricsPreview__when-latency">p95 http_request_duration_seconds</span>
                        <span className="MetricsPreview__when-memory">process_resident_memory_bytes</span>
                    </span>
                </div>
                <div className="MetricsPreview__spark-value">
                    <span className="MetricsPreview__swap">
                        <span className="MetricsPreview__when-latency">412 ms</span>
                        <span className="MetricsPreview__when-memory">1.4 GB</span>
                    </span>
                    <span className="MetricsPreview__spark-window">last 60 min</span>
                </div>
                <svg
                    className="MetricsPreview__spark-svg"
                    viewBox="0 0 100 40"
                    preserveAspectRatio="none"
                    aria-hidden="true"
                >
                    <g className="MetricsPreview__spark-g MetricsPreview__when-latency">
                        <path className="MetricsPreview__spark-area" d={areaPath(LINE_LATENCY)} />
                        <path
                            className="MetricsPreview__spark-line"
                            d={LINE_LATENCY}
                            vectorEffect="non-scaling-stroke"
                        />
                        <path
                            className="MetricsPreview__spark-trace"
                            d={LINE_LATENCY}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                    </g>
                    <g className="MetricsPreview__spark-g MetricsPreview__when-memory">
                        <path className="MetricsPreview__spark-area" d={areaPath(LINE_MEMORY)} />
                        <path
                            className="MetricsPreview__spark-line"
                            d={LINE_MEMORY}
                            vectorEffect="non-scaling-stroke"
                        />
                        <path
                            className="MetricsPreview__spark-trace"
                            d={LINE_MEMORY}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                    </g>
                </svg>
            </div>
        </div>
    )
}
