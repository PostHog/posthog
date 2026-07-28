import './ExperimentPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the experiments empty state: a running experiment's results
 * card wired to a mini app, so picking a variant shows what users in it see. The whole
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
                        <span className="ExpPreview__variant-name">control</span>
                        <span className="ExpPreview__variant-metric">3.1%</span>
                        <span className="ExpPreview__track">
                            <span className="ExpPreview__fill" style={{ '--w': '58%' } as React.CSSProperties} />
                        </span>
                    </label>
                    <label htmlFor="exp-preview-test" className="ExpPreview__variant ExpPreview__variant--test">
                        <span className="ExpPreview__variant-name">one-click</span>
                        <span className="ExpPreview__badge">Leading</span>
                        <span className="ExpPreview__variant-metric">4.6%</span>
                        <span className="ExpPreview__track">
                            <span
                                className="ExpPreview__fill ExpPreview__fill--winner"
                                style={{ '--w': '86%' } as React.CSSProperties}
                            />
                        </span>
                    </label>
                </div>

                <div className="ExpPreview__summary">96% probability the one-click variant wins · 12,481 exposures</div>
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
                    <div className="ExpPreview__hint">Select a variant above to preview what its users see.</div>
                </div>
            </div>
        </div>
    )
}
