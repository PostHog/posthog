import './HeatmapsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored daily series of clicks on the page's primary button.
const LINE = 'M 0 30 L 14 27 L 28 29 L 42 22 L 56 24 L 70 16 L 84 14 L 100 9'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the heatmaps empty state: a saved heatmap of a landing page
 * with two overlays, clicks and scroll depth, plus the stat card for its primary button.
 * A hidden radio pair drives the overlay switch via `:checked ~` styles - no timers or
 * state, per the preview rules in the `building-product-empty-states` skill. Both
 * overlays share one grid cell and crossfade, so switching never moves the page.
 */
export function HeatmapsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('HeatmapsPreview', isStatic && 'HeatmapsPreview--static')}>
            {/* Overlay choice, before both cards so `:checked ~` can style them. */}
            <input
                type="radio"
                name="heatmaps-preview-overlay"
                id="heatmaps-preview-clicks"
                className="HeatmapsPreview__radio HeatmapsPreview__radio--clicks"
                defaultChecked
            />
            <input
                type="radio"
                name="heatmaps-preview-overlay"
                id="heatmaps-preview-scroll"
                className="HeatmapsPreview__radio HeatmapsPreview__radio--scroll"
            />

            <div className="HeatmapsPreview__panel">
                <div className="HeatmapsPreview__head">
                    <span className="HeatmapsPreview__title">Pricing page</span>
                    <div className="HeatmapsPreview__segments" role="group" aria-label="Overlay">
                        <label htmlFor="heatmaps-preview-clicks" className="HeatmapsPreview__segment">
                            Clicks
                        </label>
                        <label htmlFor="heatmaps-preview-scroll" className="HeatmapsPreview__segment">
                            Scroll depth
                        </label>
                    </div>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="HeatmapsPreview__chrome" aria-hidden="true">
                    <span className="HeatmapsPreview__chrome-dot" />
                    <span className="HeatmapsPreview__chrome-dot" />
                    <span className="HeatmapsPreview__chrome-dot" />
                    <span className="HeatmapsPreview__url">example.com/pricing</span>
                </div>

                <div className="HeatmapsPreview__page" aria-hidden="true">
                    <div className="HeatmapsPreview__nav">
                        <span className="HeatmapsPreview__logo" />
                        <span className="HeatmapsPreview__nav-item" />
                        <span className="HeatmapsPreview__nav-item" />
                        <span className="HeatmapsPreview__nav-item HeatmapsPreview__nav-item--wide" />
                    </div>
                    <div className="HeatmapsPreview__hero">
                        <span className="HeatmapsPreview__line HeatmapsPreview__line--title" />
                        <span className="HeatmapsPreview__line HeatmapsPreview__line--sub" />
                        <span className="HeatmapsPreview__button">Start free</span>
                    </div>
                    <div className="HeatmapsPreview__plans">
                        <span className="HeatmapsPreview__plan" />
                        <span className="HeatmapsPreview__plan HeatmapsPreview__plan--featured" />
                        <span className="HeatmapsPreview__plan" />
                    </div>

                    <div className="HeatmapsPreview__overlays">
                        <div className="HeatmapsPreview__overlay HeatmapsPreview__overlay--clicks">
                            <span className="HeatmapsPreview__blob HeatmapsPreview__blob--hot" />
                            <span className="HeatmapsPreview__blob HeatmapsPreview__blob--warm" />
                            <span className="HeatmapsPreview__blob HeatmapsPreview__blob--nav" />
                            <span className="HeatmapsPreview__blob HeatmapsPreview__blob--plan" />
                            <span className="HeatmapsPreview__rage">
                                <span className="HeatmapsPreview__rage-ring" />
                                <span className="HeatmapsPreview__rage-label">Rage clicks</span>
                            </span>
                        </div>
                        <div className="HeatmapsPreview__overlay HeatmapsPreview__overlay--scroll">
                            <span className="HeatmapsPreview__band HeatmapsPreview__band--1">100%</span>
                            <span className="HeatmapsPreview__band HeatmapsPreview__band--2">81%</span>
                            <span className="HeatmapsPreview__band HeatmapsPreview__band--3">46%</span>
                            <span className="HeatmapsPreview__band HeatmapsPreview__band--4">17%</span>
                        </div>
                    </div>
                </div>
            </div>

            <div className="HeatmapsPreview__stat">
                <div className="HeatmapsPreview__spark-head">
                    <span className="HeatmapsPreview__spark-title HeatmapsPreview__swap">
                        <span className="HeatmapsPreview__when-clicks">Clicks on "Start free"</span>
                        <span className="HeatmapsPreview__when-scroll">Visitors reaching the plans</span>
                    </span>
                    <span className="HeatmapsPreview__spark-caption">Last 7 days</span>
                </div>
                <div className="HeatmapsPreview__spark-value HeatmapsPreview__swap">
                    <span className="HeatmapsPreview__when-clicks">1,284</span>
                    <span className="HeatmapsPreview__when-scroll">46%</span>
                </div>
                <svg
                    className="HeatmapsPreview__spark-svg"
                    viewBox="0 0 100 40"
                    preserveAspectRatio="none"
                    aria-hidden="true"
                >
                    <path className="HeatmapsPreview__spark-area" d={areaPath(LINE)} />
                    <path className="HeatmapsPreview__spark-line" d={LINE} vectorEffect="non-scaling-stroke" />
                    <path
                        className="HeatmapsPreview__spark-trace"
                        d={LINE}
                        pathLength={100}
                        vectorEffect="non-scaling-stroke"
                    />
                </svg>
                <span className="HeatmapsPreview__footer HeatmapsPreview__swap">
                    <span className="HeatmapsPreview__when-clicks">
                        37 rage clicks on the plan toggle. Nothing there responds to a click.
                    </span>
                    <span className="HeatmapsPreview__when-scroll">
                        More than half of visitors leave before they see a price.
                    </span>
                </span>
            </div>
        </div>
    )
}
