import './FeatureFlagPreview.scss'

import * as noir1Png from '@posthog/brand/hoggies/png/noir-1'
import * as partyPng from '@posthog/brand/hoggies/png/party'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored sparkline geometry for the conversion card. Both series share the same
// baseline; the "on" series steps up at the release point (x=55), where the marker sits.
const BASELINE = 'M 0 30.5 L 10 29 L 20 31 L 30 28.5 L 40 30.8 L 50 29.2'
const LINE_OFF = `${BASELINE} L 60 31 L 70 28.8 L 80 30.9 L 90 29 L 100 30.6`
const LINE_ON = `${BASELINE} L 55 29.8 L 62 16 L 70 15 L 78 13.5 L 86 14.5 L 100 12.5`

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the feature flags empty state: a mini flag list wired to a
 * mini app and a conversion sparkline, so flipping the hero flag re-skins the app's
 * checkout UI and steps the conversion chart up at the release marker. The whole
 * interaction is one hidden checkbox driving `:checked ~` styles - no timers or state,
 * per the preview rules in the `building-product-empty-states` skill. On/off pairs are
 * stacked in `__swap` grids and crossfaded, so flipping never changes the layout's size.
 */
export function FeatureFlagPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('FlagPreview', isStatic && 'FlagPreview--static')}>
            {/* Flag state, before all three cards so `:checked ~` can style them. */}
            <input type="checkbox" id="flag-preview-toggle" className="FlagPreview__checkbox" />

            <div className="FlagPreview__panel">
                <div className="FlagPreview__head">
                    <span className="FlagPreview__title">Feature flags</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="FlagPreview__rows">
                    <div className="FlagPreview__row">
                        <span className="FlagPreview__key">dark-mode</span>
                        <span className="FlagPreview__bar">
                            <span className="FlagPreview__bar-fill" style={{ '--w': '100%' } as React.CSSProperties} />
                        </span>
                        <span className="FlagPreview__rollout">100%</span>
                        <span className="FlagPreview__switch FlagPreview__switch--on" aria-hidden="true" />
                    </div>
                    <label htmlFor="flag-preview-toggle" className="FlagPreview__row FlagPreview__row--hero">
                        <span className="FlagPreview__key">one-click-checkout</span>
                        <span className="FlagPreview__bar">
                            <span className="FlagPreview__bar-fill FlagPreview__bar-fill--hero" />
                        </span>
                        <span className="FlagPreview__swap">
                            <span className="FlagPreview__rollout FlagPreview__when-off">0%</span>
                            <span className="FlagPreview__rollout FlagPreview__rollout--live FlagPreview__when-on">
                                100%
                            </span>
                        </span>
                        <span className="FlagPreview__switch" aria-hidden="true" />
                    </label>
                    <div className="FlagPreview__row">
                        <span className="FlagPreview__key">beta-invites</span>
                        <span className="FlagPreview__bar">
                            <span className="FlagPreview__bar-fill" style={{ '--w': '25%' } as React.CSSProperties} />
                        </span>
                        <span className="FlagPreview__rollout">25%</span>
                        <span className="FlagPreview__switch FlagPreview__switch--on" aria-hidden="true" />
                    </div>
                </div>

                <div className="FlagPreview__hint FlagPreview__swap">
                    <span className="FlagPreview__when-off">Flip the flag to release it in the app below.</span>
                    <span className="FlagPreview__when-on">Live for everyone. Flip it off to roll back.</span>
                </div>
            </div>

            <div className="FlagPreview__app">
                <div className="FlagPreview__chrome">
                    <span className="FlagPreview__chrome-dot" />
                    <span className="FlagPreview__chrome-dot" />
                    <span className="FlagPreview__chrome-dot" />
                    <span className="FlagPreview__url">yourapp.com/checkout</span>
                </div>
                <div className="FlagPreview__screen">
                    <div className="FlagPreview__item">
                        <span className="FlagPreview__item-blob FlagPreview__swap" aria-hidden="true">
                            <img src={noir1Png.src} alt="" className="FlagPreview__hog--noir FlagPreview__when-off" />
                            <img src={partyPng.src} alt="" className="FlagPreview__hog--party FlagPreview__when-on" />
                        </span>
                        <div className="FlagPreview__item-copy">
                            <span className="FlagPreview__item-name">Hedgehog plushie</span>
                            <span className="FlagPreview__item-price">$28.00</span>
                        </div>
                    </div>
                    <div className="FlagPreview__express FlagPreview__when-on">
                        Express checkout enabled for this order
                    </div>
                    <div className="FlagPreview__cta">
                        <span className="FlagPreview__when-off">Proceed to checkout</span>
                        <span className="FlagPreview__when-on">Buy now with 1 click</span>
                    </div>
                    <div className="FlagPreview__console">
                        <span className="FlagPreview__console-key">one-click-checkout</span>
                        <span className="FlagPreview__swap">
                            <span className="FlagPreview__console-val FlagPreview__when-off">: false</span>
                            <span className="FlagPreview__console-val FlagPreview__console-val--on FlagPreview__when-on">
                                : true
                            </span>
                        </span>
                    </div>
                </div>
            </div>

            <div className="FlagPreview__spark">
                <div className="FlagPreview__spark-head">
                    <span className="FlagPreview__spark-title">Checkout conversion · 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="FlagPreview__spark-value">
                    <span className="FlagPreview__swap">
                        <span className="FlagPreview__when-off">3.1%</span>
                        <span className="FlagPreview__when-on">4.6%</span>
                    </span>
                    <span className="FlagPreview__spark-delta FlagPreview__when-on">▲ 48%</span>
                </div>

                <div className="FlagPreview__spark-chart">
                    <span className="FlagPreview__release FlagPreview__when-on">Released</span>
                    <svg
                        className="FlagPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <g className="FlagPreview__spark-g FlagPreview__when-off">
                            <path className="FlagPreview__spark-area" d={areaPath(LINE_OFF)} />
                            <path className="FlagPreview__spark-line" d={LINE_OFF} vectorEffect="non-scaling-stroke" />
                            <path
                                className="FlagPreview__spark-trace"
                                d={LINE_OFF}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                        <g className="FlagPreview__spark-g FlagPreview__when-on">
                            <line
                                className="FlagPreview__spark-marker"
                                x1="55"
                                y1="4"
                                x2="55"
                                y2="40"
                                vectorEffect="non-scaling-stroke"
                            />
                            <path className="FlagPreview__spark-area" d={areaPath(LINE_ON)} />
                            <path className="FlagPreview__spark-line" d={LINE_ON} vectorEffect="non-scaling-stroke" />
                            <path
                                className="FlagPreview__spark-trace"
                                d={LINE_ON}
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
