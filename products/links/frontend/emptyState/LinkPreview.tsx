import './LinkPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import { playMeep } from 'products/signals/frontend/inbox/components/onboarding/meep'

// Hand-authored 7-day click series: one tiny sparkline per link row, plus a pair of
// larger series for the stat card (one per selectable link).
const ROW_SPARKS = [
    'M 0 10 L 6.6 8.5 L 13.3 9 L 20 7 L 26.6 7.6 L 33.3 5 L 40 3',
    'M 0 9 L 6.6 9.5 L 13.3 7.5 L 20 8 L 26.6 6 L 33.3 6.6 L 40 4.5',
    'M 0 8 L 6.6 8.6 L 13.3 7.8 L 20 8.4 L 26.6 7.4 L 33.3 8 L 40 7',
]
const LINE_A = 'M 0 32 L 10 30 L 20 30.8 L 30 27 L 40 27.8 L 50 24 L 60 25 L 70 20.5 L 80 19 L 90 15.5 L 100 13'
const LINE_B = 'M 0 33 L 10 32 L 20 32.4 L 30 30 L 40 30.8 L 50 28 L 60 28.8 L 70 26 L 80 25 L 90 22.5 L 100 21'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the links empty state: the link list wired to a mini
 * browser and a clicks stat card, so picking a link shows the page its visitors land
 * on. The whole interaction is two hidden radios driving `:checked ~` styles - no
 * timers or state, per the preview rules in the `building-product-empty-states`
 * skill. Link variants are stacked in `__swap` grids and crossfaded, so switching
 * never changes the layout's size.
 */
export function LinkPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('LinkPreview', isStatic && 'LinkPreview--static')}>
            {/* Link selection, before all three cards so `:checked ~` can style them. */}
            <input
                type="radio"
                name="link-preview-link"
                id="link-preview-a"
                defaultChecked
                className="LinkPreview__radio"
            />
            <input type="radio" name="link-preview-link" id="link-preview-b" className="LinkPreview__radio" />

            <div className="LinkPreview__panel">
                <div className="LinkPreview__head">
                    <span className="LinkPreview__title">Links</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="LinkPreview__rows">
                    <label htmlFor="link-preview-a" className="LinkPreview__row LinkPreview__row--a">
                        <span className="LinkPreview__vradio LinkPreview__vradio--a" aria-hidden="true" />
                        <span className="LinkPreview__link">
                            <span className="LinkPreview__key">phog.gg/spring-sale</span>
                            <span className="LinkPreview__dest">yourstore.com/spring-sale</span>
                        </span>
                        <svg className="LinkPreview__row-spark" viewBox="0 0 40 12" aria-hidden="true">
                            <path d={ROW_SPARKS[0]} vectorEffect="non-scaling-stroke" />
                        </svg>
                        <span className="LinkPreview__clicks">1,284</span>
                    </label>
                    <label htmlFor="link-preview-b" className="LinkPreview__row LinkPreview__row--b">
                        <span className="LinkPreview__vradio LinkPreview__vradio--b" aria-hidden="true" />
                        <span className="LinkPreview__link">
                            <span className="LinkPreview__key">phog.gg/podcast</span>
                            <span className="LinkPreview__dest">yourshow.fm/episode-42</span>
                        </span>
                        <svg className="LinkPreview__row-spark" viewBox="0 0 40 12" aria-hidden="true">
                            <path d={ROW_SPARKS[1]} vectorEffect="non-scaling-stroke" />
                        </svg>
                        <span className="LinkPreview__clicks">967</span>
                    </label>
                    <div className="LinkPreview__row LinkPreview__row--static">
                        <span className="LinkPreview__vradio LinkPreview__vradio--blank" aria-hidden="true" />
                        <span className="LinkPreview__link">
                            <span className="LinkPreview__key">phog.gg/qr-menu</span>
                            <span className="LinkPreview__dest">yourcafe.com/menu</span>
                        </span>
                        <svg className="LinkPreview__row-spark" viewBox="0 0 40 12" aria-hidden="true">
                            <path d={ROW_SPARKS[2]} vectorEffect="non-scaling-stroke" />
                        </svg>
                        <span className="LinkPreview__clicks">412</span>
                    </div>
                </div>

                <div className="LinkPreview__hint">Pick a link to preview where it takes people.</div>
            </div>

            <div className="LinkPreview__app">
                <div className="LinkPreview__chrome">
                    <span className="LinkPreview__chrome-dot" />
                    <span className="LinkPreview__chrome-dot" />
                    <span className="LinkPreview__chrome-dot" />
                    <span className="LinkPreview__swap LinkPreview__url">
                        <span className="LinkPreview__on-a">phog.gg/spring-sale</span>
                        <span className="LinkPreview__on-b">phog.gg/podcast</span>
                    </span>
                </div>
                <div className="LinkPreview__redirect">
                    <span className="LinkPreview__redirect-arrow" aria-hidden="true">
                        →
                    </span>
                    <span className="LinkPreview__swap">
                        <span className="LinkPreview__on-a">Redirects to yourstore.com/spring-sale</span>
                        <span className="LinkPreview__on-b">Redirects to yourshow.fm/episode-42</span>
                    </span>
                </div>
                <div className="LinkPreview__screen">
                    <span className="LinkPreview__swap LinkPreview__page-title">
                        <span className="LinkPreview__on-a">Spring sale</span>
                        <span className="LinkPreview__on-b">Episode 42</span>
                    </span>
                    <span className="LinkPreview__swap LinkPreview__page-sub">
                        <span className="LinkPreview__on-a">20% off sitewide, this week only</span>
                        <span className="LinkPreview__on-b">How small teams ship faster</span>
                    </span>
                    <span className="LinkPreview__swap LinkPreview__page-cta">
                        <span className="LinkPreview__on-a">Shop the sale</span>
                        <button type="button" className="LinkPreview__on-b LinkPreview__play" onClick={playMeep}>
                            Play episode
                        </button>
                    </span>
                </div>
            </div>

            <div className="LinkPreview__spark">
                <div className="LinkPreview__spark-head">
                    <span className="LinkPreview__swap LinkPreview__spark-title">
                        <span className="LinkPreview__on-a">Clicks · phog.gg/spring-sale · 7 days</span>
                        <span className="LinkPreview__on-b">Clicks · phog.gg/podcast · 7 days</span>
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="LinkPreview__spark-value">
                    <span className="LinkPreview__swap">
                        <span className="LinkPreview__on-a">1,284</span>
                        <span className="LinkPreview__on-b">967</span>
                    </span>
                    <span className="LinkPreview__spark-note">total clicks</span>
                </div>

                <div className="LinkPreview__spark-chart">
                    <svg
                        className="LinkPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <g className="LinkPreview__spark-g LinkPreview__on-a">
                            <path className="LinkPreview__spark-area" d={areaPath(LINE_A)} />
                            <path className="LinkPreview__spark-line" d={LINE_A} vectorEffect="non-scaling-stroke" />
                            <path
                                className="LinkPreview__spark-trace"
                                d={LINE_A}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                        <g className="LinkPreview__spark-g LinkPreview__on-b">
                            <path className="LinkPreview__spark-area" d={areaPath(LINE_B)} />
                            <path className="LinkPreview__spark-line" d={LINE_B} vectorEffect="non-scaling-stroke" />
                            <path
                                className="LinkPreview__spark-trace"
                                d={LINE_B}
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
