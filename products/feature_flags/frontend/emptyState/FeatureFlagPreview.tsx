import './FeatureFlagPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the feature flags empty state: a mini flag list wired to a
 * mini app, so flipping the hero flag visibly changes the app's checkout UI. The whole
 * interaction is one hidden checkbox driving `:checked ~` styles - no timers or state,
 * per the preview rules in the `building-product-empty-states` skill.
 */
export function FeatureFlagPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('FlagPreview', isStatic && 'FlagPreview--static')}>
            {/* Flag state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="flag-preview-toggle" className="FlagPreview__checkbox" />

            <div className="FlagPreview__panel">
                <div className="FlagPreview__head">
                    <span className="FlagPreview__title">Feature flags</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="FlagPreview__rows">
                    <div className="FlagPreview__row">
                        <span className="FlagPreview__key">dark-mode</span>
                        <span className="FlagPreview__rollout">100%</span>
                        <span className="FlagPreview__switch FlagPreview__switch--on" aria-hidden="true" />
                    </div>
                    <label htmlFor="flag-preview-toggle" className="FlagPreview__row FlagPreview__row--hero">
                        <span className="FlagPreview__key">one-click-checkout</span>
                        <span className="FlagPreview__rollout FlagPreview__when-off">0%</span>
                        <span className="FlagPreview__rollout FlagPreview__rollout--live FlagPreview__when-on">
                            100%
                        </span>
                        <span className="FlagPreview__switch" aria-hidden="true" />
                    </label>
                    <div className="FlagPreview__row">
                        <span className="FlagPreview__key">beta-invites</span>
                        <span className="FlagPreview__rollout">25%</span>
                        <span className="FlagPreview__switch FlagPreview__switch--on" aria-hidden="true" />
                    </div>
                </div>

                <div className="FlagPreview__hint">
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
                        <span className="FlagPreview__item-blob" aria-hidden="true" />
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
                </div>
            </div>
        </div>
    )
}
