import './SubscriptionsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored weekly series for the snapshot that gets delivered.
const LINE = 'M 0 28 L 14 25 L 28 27 L 42 20 L 56 22 L 70 14 L 84 12 L 100 7'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the subscriptions empty state: a scheduled dashboard and the
 * message it sends. Switching the destination re-addresses the delivery below, which is
 * the whole choice a subscription makes. One hidden checkbox drives it via `:checked ~`
 * styles - no timers or state, per the preview rules in the `building-product-empty-states`
 * skill. Before/after pairs share a `__swap` grid cell and crossfade, so nothing moves.
 */
export function SubscriptionsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('SubscriptionPreview', isStatic && 'SubscriptionPreview--static')}>
            {/* Email state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="subscription-preview-channel" className="SubscriptionPreview__checkbox" />

            <div className="SubscriptionPreview__schedule">
                <div className="SubscriptionPreview__head">
                    <span className="SubscriptionPreview__title">Weekly metrics</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="SubscriptionPreview__rows">
                    <div className="SubscriptionPreview__row">
                        <span className="SubscriptionPreview__label">Sends</span>
                        <span className="SubscriptionPreview__value">Every Monday at 9:00</span>
                    </div>

                    <label
                        htmlFor="subscription-preview-channel"
                        className="SubscriptionPreview__row SubscriptionPreview__row--pick"
                    >
                        <span className="SubscriptionPreview__label">To</span>
                        <span className="SubscriptionPreview__value SubscriptionPreview__swap">
                            <span className="SubscriptionPreview__when-before">Slack, #product-updates</span>
                            <span className="SubscriptionPreview__when-after">Email, the growth team</span>
                        </span>
                        <span className="SubscriptionPreview__switch SubscriptionPreview__swap">
                            <span className="SubscriptionPreview__when-before">Send by email instead</span>
                            <span className="SubscriptionPreview__when-after">Send to Slack instead</span>
                        </span>
                    </label>
                </div>
            </div>

            <div className="SubscriptionPreview__delivery">
                <div className="SubscriptionPreview__delivery-head SubscriptionPreview__swap">
                    <span className="SubscriptionPreview__when-before">
                        <span className="SubscriptionPreview__avatar" aria-hidden="true" />
                        <span className="SubscriptionPreview__sender">PostHog</span>
                        <span className="SubscriptionPreview__meta">9:00 AM in #product-updates</span>
                    </span>
                    <span className="SubscriptionPreview__when-after">
                        <span className="SubscriptionPreview__avatar" aria-hidden="true" />
                        <span className="SubscriptionPreview__sender">Weekly metrics is ready</span>
                        <span className="SubscriptionPreview__meta">to growth@example.com</span>
                    </span>
                </div>

                <div className="SubscriptionPreview__body">
                    <span className="SubscriptionPreview__snapshot-title">Sign-ups, last 7 days</span>
                    <svg
                        className="SubscriptionPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="SubscriptionPreview__spark-area" d={areaPath(LINE)} />
                        <path className="SubscriptionPreview__spark-line" d={LINE} vectorEffect="non-scaling-stroke" />
                        <path
                            className="SubscriptionPreview__spark-trace"
                            d={LINE}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                    </svg>
                    <span className="SubscriptionPreview__footer">Next delivery in 3 days</span>
                </div>
            </div>
        </div>
    )
}
