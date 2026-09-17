import './ProductAnalyticsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// One combined series, then the same total split three ways. The parts stay under the
// whole at every point, so the breakdown reads as a decomposition rather than new data.
const LINE_TOTAL = 'M 0 30 L 16 27 L 33 28 L 50 22 L 66 24 L 83 17 L 100 13'
const LINE_CHROME = 'M 0 33 L 16 31 L 33 31 L 50 26 L 66 28 L 83 22 L 100 19'
const LINE_SAFARI = 'M 0 36 L 16 35 L 33 35 L 50 32 L 66 33 L 83 30 L 100 28'
const LINE_FIREFOX = 'M 0 38 L 16 38 L 33 37 L 50 36 L 66 36 L 83 35 L 100 34'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the product analytics empty state: one insight, and what
 * a breakdown does to it. Turning the breakdown on splits a single pageview line into
 * one line per browser and fills in the legend. One hidden checkbox drives it via
 * `:checked ~` styles - no timers or state, per the preview rules in the
 * `building-product-empty-states` skill. Before/after pairs are stacked in `__swap`
 * grids and crossfaded, so nothing shifts.
 */
export function ProductAnalyticsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('InsightPreview', isStatic && 'InsightPreview--static')}>
            {/* Breakdown state, before the card so `:checked ~` can style it. */}
            <input type="checkbox" id="insight-preview-breakdown" className="InsightPreview__checkbox" />

            <div className="InsightPreview__card">
                <div className="InsightPreview__head">
                    <span className="InsightPreview__title">Pageviews, last 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="InsightPreview__query">
                    <span className="InsightPreview__series-dot" aria-hidden="true" />
                    <span className="InsightPreview__series">Pageview</span>
                    <label htmlFor="insight-preview-breakdown" className="InsightPreview__breakdown">
                        <span className="InsightPreview__swap">
                            <span className="InsightPreview__when-before">Break down by browser</span>
                            <span className="InsightPreview__when-after">Breakdown: Browser</span>
                        </span>
                    </label>
                </div>

                <div className="InsightPreview__plot">
                    <svg
                        className="InsightPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <g className="InsightPreview__spark-g InsightPreview__when-before">
                            <path className="InsightPreview__spark-area" d={areaPath(LINE_TOTAL)} />
                            <path
                                className="InsightPreview__spark-line"
                                d={LINE_TOTAL}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="InsightPreview__spark-trace"
                                d={LINE_TOTAL}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                        <g className="InsightPreview__spark-g InsightPreview__when-after">
                            <path
                                className="InsightPreview__spark-line InsightPreview__spark-line--chrome"
                                d={LINE_CHROME}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="InsightPreview__spark-line InsightPreview__spark-line--safari"
                                d={LINE_SAFARI}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="InsightPreview__spark-line InsightPreview__spark-line--firefox"
                                d={LINE_FIREFOX}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="InsightPreview__spark-trace"
                                d={LINE_CHROME}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                    </svg>
                </div>

                <div className="InsightPreview__legend">
                    <div className="InsightPreview__legend-slot InsightPreview__swap">
                        <span className="InsightPreview__legend-spacer InsightPreview__when-before" />
                        <div className="InsightPreview__legend-rows InsightPreview__when-after">
                            <span className="InsightPreview__legend-row">
                                <span className="InsightPreview__key InsightPreview__key--chrome" aria-hidden="true" />
                                Chrome
                                <span className="InsightPreview__legend-value">18,204</span>
                            </span>
                            <span className="InsightPreview__legend-row">
                                <span className="InsightPreview__key InsightPreview__key--safari" aria-hidden="true" />
                                Safari
                                <span className="InsightPreview__legend-value">6,918</span>
                            </span>
                            <span className="InsightPreview__legend-row">
                                <span className="InsightPreview__key InsightPreview__key--firefox" aria-hidden="true" />
                                Firefox
                                <span className="InsightPreview__legend-value">2,140</span>
                            </span>
                        </div>
                    </div>
                </div>

                <div className="InsightPreview__hint InsightPreview__swap">
                    <span className="InsightPreview__when-before">Break the total down to see who is behind it.</span>
                    <span className="InsightPreview__when-after">
                        Save this insight, or drop it on a dashboard. Click again to undo.
                    </span>
                </div>
            </div>
        </div>
    )
}
