import './WebAnalyticsPreview.scss'

import { sparkPaths } from 'lib/components/ProductEmptyState/previewSparkline'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

const ALL_TRAFFIC = sparkPaths([1480, 1720, 2310, 1890, 2040, 1650, 2180])
const NEWSLETTER_TRAFFIC = sparkPaths([40, 30, 820, 260, 120, 70, 50])

interface ChannelRow {
    name: string
    visitors: string
    barClassName: string
}

const CHANNELS: ChannelRow[] = [
    { name: 'Direct', visitors: '4.9k', barClassName: 'WebPreview__bar--direct' },
    { name: 'Google', visitors: '3.6k', barClassName: 'WebPreview__bar--google' },
    { name: 'LinkedIn', visitors: '1.1k', barClassName: 'WebPreview__bar--linkedin' },
]

const PAGES = [
    { path: '/', visitors: '6.8k' },
    { path: '/pricing', visitors: '2.4k' },
    { path: '/docs', visitors: '1.9k' },
]

/**
 * Example-data preview for the web analytics empty state: visitors over the week, the channels they
 * came from, and the pages they landed on. Clicking the newsletter channel filters the chart and
 * points at the page it sent people to. One hidden checkbox drives it via `:checked ~` styles - no
 * timers or state, per the preview rules in the `building-product-empty-states` skill.
 */
export function WebAnalyticsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('WebPreview', isStatic && 'WebPreview--static')}>
            {/* Filter state, before every card so `:checked ~` can style them. */}
            <input type="checkbox" id="web-preview-filter" className="WebPreview__checkbox" />

            <div className="WebPreview__card">
                <div className="WebPreview__head">
                    <span className="WebPreview__title">
                        <span className="WebPreview__live-dot" aria-hidden="true" />
                        <span className="WebPreview__swap">
                            <span className="WebPreview__when-idle">Visitors · last 7 days</span>
                            <span className="WebPreview__when-filtered">Visitors from Newsletter</span>
                        </span>
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="WebPreview__stat">
                    <span className="WebPreview__swap">
                        <span className="WebPreview__when-idle WebPreview__stat-value">12.2k</span>
                        <span className="WebPreview__when-filtered WebPreview__stat-value">1.4k</span>
                    </span>
                    <span className="WebPreview__swap">
                        <span className="WebPreview__when-idle WebPreview__stat-change">+18% vs last week</span>
                        <span className="WebPreview__when-filtered WebPreview__stat-change">peaked on Wednesday</span>
                    </span>
                </div>
                <div className="WebPreview__swap WebPreview__chart">
                    <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="WebPreview__when-idle">
                        <path d={ALL_TRAFFIC.area} className="WebPreview__area" />
                        <path d={ALL_TRAFFIC.line} className="WebPreview__line" />
                    </svg>
                    <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="WebPreview__when-filtered">
                        <path d={NEWSLETTER_TRAFFIC.area} className="WebPreview__area" />
                        <path d={NEWSLETTER_TRAFFIC.line} className="WebPreview__line" />
                    </svg>
                </div>
            </div>

            <div className="WebPreview__columns">
                <div className="WebPreview__card">
                    <div className="WebPreview__head">
                        <span className="WebPreview__title">Channels</span>
                    </div>
                    <div className="WebPreview__rows">
                        {CHANNELS.slice(0, 2).map((channel) => (
                            <WebPreviewRow key={channel.name} {...channel} />
                        ))}
                        <label htmlFor="web-preview-filter" className="WebPreview__row WebPreview__row--hero">
                            <span className="WebPreview__bar WebPreview__bar--newsletter" />
                            <span className="WebPreview__name">Newsletter</span>
                            <span className="WebPreview__count">1.4k</span>
                        </label>
                        <WebPreviewRow {...CHANNELS[2]} />
                    </div>
                </div>

                <div className="WebPreview__card">
                    <div className="WebPreview__head">
                        <span className="WebPreview__title">Top pages</span>
                    </div>
                    <div className="WebPreview__rows">
                        {PAGES.map((page) => (
                            <div key={page.path} className="WebPreview__row">
                                <span className="WebPreview__name WebPreview__name--mono">{page.path}</span>
                                <span className="WebPreview__count">{page.visitors}</span>
                            </div>
                        ))}
                        <div className="WebPreview__row WebPreview__row--match">
                            <span className="WebPreview__name WebPreview__name--mono">/blog/example-post</span>
                            <span className="WebPreview__count">1.2k</span>
                        </div>
                    </div>
                </div>
            </div>

            <div className="WebPreview__hint WebPreview__swap">
                <span className="WebPreview__when-idle">Click a channel to see the traffic it brought.</span>
                <span className="WebPreview__when-filtered">
                    The newsletter sent people to one post. Click again to clear the filter.
                </span>
            </div>
        </div>
    )
}

function WebPreviewRow({ name, visitors, barClassName }: ChannelRow): JSX.Element {
    return (
        <div className="WebPreview__row">
            <span className={cn('WebPreview__bar', barClassName)} />
            <span className="WebPreview__name">{name}</span>
            <span className="WebPreview__count">{visitors}</span>
        </div>
    )
}
