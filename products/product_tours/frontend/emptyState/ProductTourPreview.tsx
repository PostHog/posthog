import './ProductTourPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored rising completion series for the stat card sparkline.
const SPARK_LINE = 'M 0 31 L 10 30 L 20 30.8 L 30 27.5 L 40 28.2 L 50 24.5 L 60 25 L 70 21.5 L 80 20 L 90 16.5 L 100 15'
const SPARK_AREA = `${SPARK_LINE} L 100 40 L 0 40 Z`

/**
 * Example-data preview for the product tours empty state: the tours list wired to a
 * mini app where the hero tour is actually playing, so clicking "Next" in the tour
 * tooltip moves the spotlight (and step counter) from one UI element to another. The
 * whole interaction is two hidden radios driving `:checked ~` styles - no timers or
 * state, per the preview rules in the `building-product-empty-states` skill. Both
 * tooltips are absolutely positioned and crossfaded, so stepping never shifts layout.
 */
export function ProductTourPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('TourPreview', isStatic && 'TourPreview--static')}>
            {/* Step state, before all cards so `:checked ~` can style them. */}
            <input
                type="radio"
                name="tour-preview-step"
                id="tour-preview-step-1"
                defaultChecked
                className="TourPreview__radio TourPreview__radio--1"
            />
            <input
                type="radio"
                name="tour-preview-step"
                id="tour-preview-step-2"
                className="TourPreview__radio TourPreview__radio--2"
            />

            <div className="TourPreview__panel">
                <div className="TourPreview__head">
                    <span className="TourPreview__title">Product tours</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="TourPreview__rows">
                    <div className="TourPreview__row TourPreview__row--hero">
                        <span className="TourPreview__name">Welcome tour</span>
                        <span className="TourPreview__kind TourPreview__kind--tour">Tour</span>
                        <span className="TourPreview__steps">3 steps</span>
                        <span className="TourPreview__status TourPreview__status--running">
                            <span className="TourPreview__status-dot" aria-hidden="true" />
                            Running
                        </span>
                    </div>
                    <div className="TourPreview__row">
                        <span className="TourPreview__name">New: usage reports</span>
                        <span className="TourPreview__kind">Announcement</span>
                        <span className="TourPreview__steps">1 step</span>
                        <span className="TourPreview__status">Draft</span>
                    </div>
                    <div className="TourPreview__row">
                        <span className="TourPreview__name">Maintenance notice</span>
                        <span className="TourPreview__kind">Banner</span>
                        <span className="TourPreview__steps">1 step</span>
                        <span className="TourPreview__status">Scheduled</span>
                    </div>
                </div>
            </div>

            <div className="TourPreview__app">
                <div className="TourPreview__chrome">
                    <span className="TourPreview__chrome-dot" />
                    <span className="TourPreview__chrome-dot" />
                    <span className="TourPreview__chrome-dot" />
                    <span className="TourPreview__url">yourapp.com/reports</span>
                </div>
                <div className="TourPreview__screen">
                    <div className="TourPreview__sidebar">
                        <span className="TourPreview__nav TourPreview__nav--target1">
                            Reports
                            <span className="TourPreview__beacon TourPreview__beacon--1" aria-hidden="true" />
                        </span>
                        <span className="TourPreview__nav">Dashboards</span>
                        <span className="TourPreview__nav">Settings</span>
                    </div>
                    <div className="TourPreview__main">
                        <span className="TourPreview__skel" style={{ '--w': '80%' } as React.CSSProperties} />
                        <span className="TourPreview__skel" style={{ '--w': '55%' } as React.CSSProperties} />
                        <span className="TourPreview__button TourPreview__button--target2">
                            Share report
                            <span className="TourPreview__beacon TourPreview__beacon--2" aria-hidden="true" />
                        </span>
                    </div>

                    {/* Both tour tooltips stay in the DOM, absolutely positioned next to
                        their targets, and crossfade - stepping never resizes the screen. */}
                    <div className="TourPreview__tip TourPreview__tip--1">
                        <span className="TourPreview__tip-text">Your usage reports live here.</span>
                        <span className="TourPreview__tip-foot">
                            <span className="TourPreview__tip-count">1 of 3</span>
                            <label htmlFor="tour-preview-step-2" className="TourPreview__tip-btn">
                                Next
                            </label>
                        </span>
                    </div>
                    <div className="TourPreview__tip TourPreview__tip--2">
                        <span className="TourPreview__tip-text">Share a report with your team.</span>
                        <span className="TourPreview__tip-foot">
                            <span className="TourPreview__tip-count">2 of 3</span>
                            <label
                                htmlFor="tour-preview-step-1"
                                className="TourPreview__tip-btn TourPreview__tip-btn--back"
                            >
                                Back
                            </label>
                        </span>
                    </div>
                </div>
            </div>

            <div className="TourPreview__spark">
                <div className="TourPreview__spark-head">
                    <span className="TourPreview__spark-title">Tour completion · Welcome tour · 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="TourPreview__spark-value">
                    68%
                    <span className="TourPreview__spark-delta">▲ 12%</span>
                </div>

                <div className="TourPreview__spark-chart">
                    <svg
                        className="TourPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="TourPreview__spark-area" d={SPARK_AREA} />
                        <path className="TourPreview__spark-line" d={SPARK_LINE} vectorEffect="non-scaling-stroke" />
                        <path
                            className="TourPreview__spark-trace"
                            d={SPARK_LINE}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                    </svg>
                </div>
            </div>
        </div>
    )
}
