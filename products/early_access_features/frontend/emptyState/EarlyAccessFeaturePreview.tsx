import './EarlyAccessFeaturePreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored rising opt-ins series for the stat card sparkline.
const SPARK_LINE = 'M 0 32 L 10 30.5 L 20 31 L 30 28 L 40 28.8 L 50 25.5 L 60 26.2 L 70 22 L 80 20.5 L 90 17 L 100 15'
const SPARK_AREA = `${SPARK_LINE} L 100 40 L 0 40 Z`

/**
 * Example-data preview for the early access features empty state: the feature roster
 * wired to a mini "labs" settings dashboard, so opting into the hero beta - like an
 * end user would - reveals the feature in the app and ticks the opt-in counter. The
 * whole interaction is one hidden checkbox driving `:checked ~` styles - no timers or
 * state, per the preview rules in the `building-product-empty-states` skill. On/off
 * pairs are stacked in `__swap` grids and crossfaded, so opting in never changes the
 * layout's size.
 */
export function EarlyAccessFeaturePreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('EafPreview', isStatic && 'EafPreview--static')}>
            {/* Opt-in state, before all three cards so `:checked ~` can style them. */}
            <input type="checkbox" id="eaf-preview-toggle" className="EafPreview__checkbox" />

            <div className="EafPreview__panel">
                <div className="EafPreview__head">
                    <span className="EafPreview__title">Early access features</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="EafPreview__rows">
                    <div className="EafPreview__row">
                        <span className="EafPreview__name">AI summaries</span>
                        <span className="EafPreview__stage EafPreview__stage--beta">Beta</span>
                        <span className="EafPreview__swap EafPreview__optins">
                            <span className="EafPreview__when-off">1,204 opted in</span>
                            <span className="EafPreview__optins--live EafPreview__when-on">1,205 opted in</span>
                        </span>
                    </div>
                    <div className="EafPreview__row">
                        <span className="EafPreview__name">New editor</span>
                        <span className="EafPreview__stage">Alpha</span>
                        <span className="EafPreview__optins">87 opted in</span>
                    </div>
                    <div className="EafPreview__row">
                        <span className="EafPreview__name">Dark charts</span>
                        <span className="EafPreview__stage EafPreview__stage--beta">Beta</span>
                        <span className="EafPreview__optins">412 opted in</span>
                    </div>
                </div>
            </div>

            <div className="EafPreview__app">
                <div className="EafPreview__chrome">
                    <span className="EafPreview__chrome-dot" />
                    <span className="EafPreview__chrome-dot" />
                    <span className="EafPreview__chrome-dot" />
                    <span className="EafPreview__url">yourapp.com/settings/labs</span>
                </div>
                <div className="EafPreview__screen">
                    <label htmlFor="eaf-preview-toggle" className="EafPreview__lab EafPreview__lab--hero">
                        <span className="EafPreview__lab-copy">
                            <span className="EafPreview__lab-name">AI summaries</span>
                            <span className="EafPreview__lab-desc">Get a summary on every report</span>
                        </span>
                        <span className="EafPreview__switch" aria-hidden="true" />
                    </label>
                    <div className="EafPreview__lab">
                        <span className="EafPreview__lab-copy">
                            <span className="EafPreview__lab-name">New editor</span>
                            <span className="EafPreview__lab-desc">Rebuilt from the ground up</span>
                        </span>
                        <span className="EafPreview__switch" aria-hidden="true" />
                    </div>
                    <div className="EafPreview__lab">
                        <span className="EafPreview__lab-copy">
                            <span className="EafPreview__lab-name">Dark charts</span>
                            <span className="EafPreview__lab-desc">High-contrast chart theme</span>
                        </span>
                        <span className="EafPreview__switch EafPreview__switch--on" aria-hidden="true" />
                    </div>

                    <div className="EafPreview__report EafPreview__swap">
                        <span className="EafPreview__report-body EafPreview__when-off">
                            <span className="EafPreview__skel" style={{ '--w': '100%' } as React.CSSProperties} />
                            <span className="EafPreview__skel" style={{ '--w': '65%' } as React.CSSProperties} />
                        </span>
                        <span className="EafPreview__report-body EafPreview__when-on">
                            <span className="EafPreview__summary">AI summary: signups up 12% this week</span>
                            <span className="EafPreview__skel" style={{ '--w': '65%' } as React.CSSProperties} />
                        </span>
                    </div>

                    <div className="EafPreview__hint EafPreview__swap">
                        <span className="EafPreview__when-off">Flip a feature on to opt this user in.</span>
                        <span className="EafPreview__when-on">Opted in. Flip it off any time.</span>
                    </div>
                </div>
            </div>

            <div className="EafPreview__spark">
                <div className="EafPreview__spark-head">
                    <span className="EafPreview__spark-title">Opt-ins · AI summaries · 7 days</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="EafPreview__spark-value">
                    <span className="EafPreview__swap">
                        <span className="EafPreview__when-off">1,204</span>
                        <span className="EafPreview__when-on">1,205</span>
                    </span>
                    <span className="EafPreview__spark-delta EafPreview__when-on">+1 just now</span>
                </div>

                <div className="EafPreview__spark-chart">
                    <svg
                        className="EafPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="EafPreview__spark-area" d={SPARK_AREA} />
                        <path className="EafPreview__spark-line" d={SPARK_LINE} vectorEffect="non-scaling-stroke" />
                        <path
                            className="EafPreview__spark-trace"
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
