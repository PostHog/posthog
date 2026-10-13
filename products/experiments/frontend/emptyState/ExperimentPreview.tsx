import './ExperimentPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the experiments empty state: a running experiment's results
 * card (variant rows, credible-interval chart, win probability) wired to a mini app,
 * so picking a variant highlights its interval and shows what its users see. The whole
 * interaction is two hidden radios driving `:checked ~` styles - no timers or state,
 * per the preview rules in the `building-product-empty-states` skill.
 */
export function ExperimentPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('ExpPreview', isStatic && 'ExpPreview--static')}>
            {/* Variant selection, before both cards so `:checked ~` can style them. */}
            <input
                type="radio"
                name="exp-preview-variant"
                id="exp-preview-control"
                defaultChecked
                className="ExpPreview__radio"
            />
            <input type="radio" name="exp-preview-variant" id="exp-preview-test" className="ExpPreview__radio" />

            <div className="ExpPreview__card">
                <div className="ExpPreview__head">
                    <span className="ExpPreview__title">checkout-cta</span>
                    <span className="ExpPreview__running">
                        <span className="ExpPreview__running-dot" aria-hidden="true" />
                        Running
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="ExpPreview__variants">
                    <label htmlFor="exp-preview-control" className="ExpPreview__variant ExpPreview__variant--control">
                        <span className="ExpPreview__vradio ExpPreview__vradio--control" aria-hidden="true" />
                        <span className="ExpPreview__variant-name">control</span>
                        <span className="ExpPreview__variant-users">6,204 users</span>
                        <span className="ExpPreview__variant-metric">3.1%</span>
                    </label>
                    <label htmlFor="exp-preview-test" className="ExpPreview__variant ExpPreview__variant--test">
                        <span className="ExpPreview__vradio ExpPreview__vradio--test" aria-hidden="true" />
                        <span className="ExpPreview__variant-name">one-click</span>
                        <span className="ExpPreview__badge">Leading</span>
                        <span className="ExpPreview__variant-users">6,277 users</span>
                        <span className="ExpPreview__variant-metric">4.6%</span>
                    </label>
                </div>

                {/* Credible-interval chart: control straddles the zero line, the test
                    variant sits clear of it. Fixed aspect (no preserveAspectRatio="none")
                    so the dots stay round. */}
                <div className="ExpPreview__chart" aria-hidden="true">
                    <svg className="ExpPreview__chart-svg" viewBox="0 0 300 60">
                        <line className="ExpPreview__axis" x1="105" y1="4" x2="105" y2="56" />
                        <g className="ExpPreview__int ExpPreview__int--control">
                            <rect className="ExpPreview__int-bar" x="66" y="14" width="78" height="8" rx="4" />
                            <circle className="ExpPreview__int-dot" cx="105" cy="18" r="3" />
                        </g>
                        <g className="ExpPreview__int ExpPreview__int--test">
                            <rect className="ExpPreview__int-bar" x="120" y="38" width="114" height="8" rx="4" />
                            <circle className="ExpPreview__int-dot" cx="177" cy="42" r="3" />
                        </g>
                    </svg>
                    <div className="ExpPreview__chart-caption">Change in conversion vs control</div>
                </div>

                <div className="ExpPreview__prob">
                    <span className="ExpPreview__prob-label">Chance one-click wins</span>
                    <span className="ExpPreview__prob-value">96%</span>
                    <span className="ExpPreview__track">
                        <span
                            className="ExpPreview__fill ExpPreview__fill--winner"
                            style={{ '--w': '96%' } as React.CSSProperties}
                        />
                    </span>
                </div>
            </div>

            <div className="ExpPreview__app">
                <div className="ExpPreview__chrome">
                    <span className="ExpPreview__chrome-dot" />
                    <span className="ExpPreview__chrome-dot" />
                    <span className="ExpPreview__chrome-dot" />
                    <span className="ExpPreview__url">yourapp.com/checkout</span>
                    <span className="ExpPreview__pill ExpPreview__pill--control">control</span>
                    <span className="ExpPreview__pill ExpPreview__pill--test">one-click</span>
                </div>
                <div className="ExpPreview__screen">
                    <div className="ExpPreview__cta ExpPreview__cta--control">Proceed to checkout</div>
                    <div className="ExpPreview__cta ExpPreview__cta--test">Buy now with 1 click</div>
                    <div className="ExpPreview__conv ExpPreview__conv--control">3.1% of visitors convert</div>
                    <div className="ExpPreview__conv ExpPreview__conv--test">4.6% of visitors convert</div>
                    <div className="ExpPreview__hint">Select a variant above to preview what its users see.</div>
                </div>
            </div>
        </div>
    )
}
