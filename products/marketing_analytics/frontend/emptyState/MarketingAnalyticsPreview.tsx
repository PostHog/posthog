import './MarketingAnalyticsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the marketing analytics empty state: ad channels with
 * spend joined to a conversion goal. Clicking the goal chip swaps the goal from
 * signups to purchases, and every conversion and ROAS figure follows. One hidden
 * checkbox drives it via `:checked ~` styles - no timers or state, per the
 * preview rules in the `building-product-empty-states` skill. Goal pairs are
 * stacked in `__swap` grids, so nothing shifts.
 */
export function MarketingAnalyticsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('MarketingPreview', isStatic && 'MarketingPreview--static')}>
            {/* Goal state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="marketing-preview-goal" className="MarketingPreview__checkbox" />

            <div className="MarketingPreview__channels">
                <div className="MarketingPreview__head">
                    <span className="MarketingPreview__title">
                        <span className="MarketingPreview__live-dot" aria-hidden="true" />
                        Channels · 30 days
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="MarketingPreview__goal-bar">
                    <span className="MarketingPreview__goal-label">Conversion goal</span>
                    <label htmlFor="marketing-preview-goal" className="MarketingPreview__goal-chip">
                        <span className="MarketingPreview__swap">
                            <span className="MarketingPreview__when-signups">signed_up</span>
                            <span className="MarketingPreview__when-purchases">purchase_completed</span>
                        </span>
                    </label>
                </div>
                <div className="MarketingPreview__rows">
                    <div className="MarketingPreview__row MarketingPreview__row--header">
                        <span>Channel</span>
                        <span>Spend</span>
                        <span>Conv.</span>
                        <span>ROAS</span>
                    </div>
                    <div className="MarketingPreview__row">
                        <span className="MarketingPreview__channel">Google Ads</span>
                        <span>$4,120</span>
                        <span className="MarketingPreview__swap">
                            <span className="MarketingPreview__when-signups">311</span>
                            <span className="MarketingPreview__when-purchases">64</span>
                        </span>
                        <span className="MarketingPreview__swap">
                            <span className="MarketingPreview__when-signups">3.4×</span>
                            <span className="MarketingPreview__when-purchases">2.2×</span>
                        </span>
                    </div>
                    <div className="MarketingPreview__row">
                        <span className="MarketingPreview__channel">Meta Ads</span>
                        <span>$2,860</span>
                        <span className="MarketingPreview__swap">
                            <span className="MarketingPreview__when-signups">402</span>
                            <span className="MarketingPreview__when-purchases">38</span>
                        </span>
                        <span className="MarketingPreview__swap">
                            <span className="MarketingPreview__when-signups">4.1×</span>
                            <span className="MarketingPreview__when-purchases">1.3×</span>
                        </span>
                    </div>
                    <div className="MarketingPreview__row">
                        <span className="MarketingPreview__channel">LinkedIn Ads</span>
                        <span>$1,240</span>
                        <span className="MarketingPreview__swap">
                            <span className="MarketingPreview__when-signups">57</span>
                            <span className="MarketingPreview__when-purchases">21</span>
                        </span>
                        <span className="MarketingPreview__swap">
                            <span className="MarketingPreview__when-signups">1.1×</span>
                            <span className="MarketingPreview__when-purchases">2.6×</span>
                        </span>
                    </div>
                </div>
                <div className="MarketingPreview__hint MarketingPreview__swap">
                    <span className="MarketingPreview__when-signups">
                        Click the goal to judge the same spend by purchases.
                    </span>
                    <span className="MarketingPreview__when-purchases">
                        Meta wins signups, Google wins revenue. Click to flip back.
                    </span>
                </div>
            </div>

            <div className="MarketingPreview__stat">
                <div className="MarketingPreview__spark-head">
                    <span className="MarketingPreview__spark-title MarketingPreview__swap">
                        <span className="MarketingPreview__when-signups">Cost per signup · blended</span>
                        <span className="MarketingPreview__when-purchases">Cost per purchase · blended</span>
                    </span>
                </div>
                <div className="MarketingPreview__spark-value">
                    <span className="MarketingPreview__swap">
                        <span className="MarketingPreview__when-signups">$10.67</span>
                        <span className="MarketingPreview__when-purchases">$66.83</span>
                    </span>
                    <span className="MarketingPreview__spark-sub">$8,220 spend</span>
                </div>
            </div>
        </div>
    )
}
