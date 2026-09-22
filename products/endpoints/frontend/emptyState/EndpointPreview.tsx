import './EndpointPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored latency sparkline geometry. Both series share the same start; the
// "materialized" series drops at the materialization point (x=55), where the marker sits.
const BASELINE = 'M 0 13 L 10 14.5 L 20 12.5 L 30 15 L 40 13.2 L 50 14.6'
const LINE_INLINE = `${BASELINE} L 60 12.8 L 70 14.9 L 80 13 L 90 15 L 100 13.4`
const LINE_MATERIALIZED = `${BASELINE} L 55 14.2 L 62 30 L 70 31.5 L 78 31 L 86 31.8 L 100 31.2`

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the endpoints empty state: a mini endpoint list wired to a
 * terminal calling one over the API and a latency sparkline, so materializing the hero
 * endpoint flips the response time from seconds to milliseconds and drops the latency
 * chart at the marker. The whole interaction is one hidden checkbox driving
 * `:checked ~` styles - no timers or state, per the preview rules in the
 * `building-product-empty-states` skill. Inline/materialized pairs are stacked in
 * `__swap` grids and crossfaded, so toggling never changes the layout's size.
 */
export function EndpointPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('EndpointPreview', isStatic && 'EndpointPreview--static')}>
            {/* Materialization state, before all three cards so `:checked ~` can style them. */}
            <input type="checkbox" id="endpoint-preview-toggle" className="EndpointPreview__checkbox" />

            <div className="EndpointPreview__panel">
                <div className="EndpointPreview__head">
                    <span className="EndpointPreview__title">Endpoints</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="EndpointPreview__rows">
                    <label
                        htmlFor="endpoint-preview-toggle"
                        className="EndpointPreview__row EndpointPreview__row--hero"
                    >
                        <span className="EndpointPreview__copy">
                            <span className="EndpointPreview__name">active-users-daily</span>
                            <span className="EndpointPreview__path">
                                /api/projects/2/endpoints/active-users-daily/run
                            </span>
                        </span>
                        <span className="EndpointPreview__swap EndpointPreview__mat">
                            <span className="EndpointPreview__when-off">Inline</span>
                            <span className="EndpointPreview__mat--live EndpointPreview__when-on">Materialized</span>
                        </span>
                        <span className="EndpointPreview__switch" aria-hidden="true" />
                    </label>
                    <div className="EndpointPreview__row">
                        <span className="EndpointPreview__copy">
                            <span className="EndpointPreview__name">revenue-by-plan</span>
                            <span className="EndpointPreview__path">/api/projects/2/endpoints/revenue-by-plan/run</span>
                        </span>
                        <span className="EndpointPreview__mat EndpointPreview__mat--live">Materialized</span>
                        <span className="EndpointPreview__switch EndpointPreview__switch--on" aria-hidden="true" />
                    </div>
                </div>

                <div className="EndpointPreview__hint EndpointPreview__swap">
                    <span className="EndpointPreview__when-off">
                        Materialize the endpoint to precompute its results.
                    </span>
                    <span className="EndpointPreview__when-on">
                        Serving precomputed results. Same API, no code changes.
                    </span>
                </div>
            </div>

            <div className="EndpointPreview__terminal">
                <div className="EndpointPreview__chrome">
                    <span className="EndpointPreview__chrome-dot" />
                    <span className="EndpointPreview__chrome-dot" />
                    <span className="EndpointPreview__chrome-dot" />
                    <span className="EndpointPreview__chrome-title">your app</span>
                </div>
                <div className="EndpointPreview__screen">
                    <div className="EndpointPreview__line">
                        <span className="EndpointPreview__prompt-char">$</span> curl
                        us.posthog.com/api/projects/2/endpoints/active-users-daily/run
                    </div>
                    <div className="EndpointPreview__line EndpointPreview__response">
                        {'{ "results": [["2026-07-28", 4102], ["2026-07-27", 3987], …] }'}
                    </div>
                    <div className="EndpointPreview__line EndpointPreview__swap">
                        <span className="EndpointPreview__when-off">
                            <span className="EndpointPreview__ok">200 OK</span>
                            <span className="EndpointPreview__timing">· 4.2s</span>
                        </span>
                        <span className="EndpointPreview__when-on">
                            <span className="EndpointPreview__ok">200 OK</span>
                            <span className="EndpointPreview__timing EndpointPreview__timing--fast">· 180ms</span>
                        </span>
                    </div>
                </div>
            </div>

            <div className="EndpointPreview__spark">
                <div className="EndpointPreview__spark-head">
                    <span className="EndpointPreview__spark-title">p95 latency · active-users-daily · 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="EndpointPreview__spark-value">
                    <span className="EndpointPreview__swap">
                        <span className="EndpointPreview__when-off">4.2s</span>
                        <span className="EndpointPreview__when-on">180ms</span>
                    </span>
                    <span className="EndpointPreview__spark-delta EndpointPreview__when-on">▼ 96%</span>
                </div>

                <div className="EndpointPreview__spark-chart">
                    <span className="EndpointPreview__marker-label EndpointPreview__when-on">Materialized</span>
                    <svg
                        className="EndpointPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <g className="EndpointPreview__spark-g EndpointPreview__when-off">
                            <path className="EndpointPreview__spark-area" d={areaPath(LINE_INLINE)} />
                            <path
                                className="EndpointPreview__spark-line"
                                d={LINE_INLINE}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="EndpointPreview__spark-trace"
                                d={LINE_INLINE}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                        <g className="EndpointPreview__spark-g EndpointPreview__when-on">
                            <line
                                className="EndpointPreview__spark-marker"
                                x1="55"
                                y1="4"
                                x2="55"
                                y2="40"
                                vectorEffect="non-scaling-stroke"
                            />
                            <path className="EndpointPreview__spark-area" d={areaPath(LINE_MATERIALIZED)} />
                            <path
                                className="EndpointPreview__spark-line"
                                d={LINE_MATERIALIZED}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="EndpointPreview__spark-trace"
                                d={LINE_MATERIALIZED}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                    </svg>
                </div>
            </div>
        </div>
    )
}
