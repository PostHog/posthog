import './WebVitalsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the web vitals empty state: the four vitals tiles and
 * the pages behind them. Clicking the failing CLS tile highlights the pages that
 * drag it down. One hidden checkbox drives it via `:checked ~` styles - no timers
 * or state, per the preview rules in the `building-product-empty-states` skill.
 * Focused/unfocused pairs are stacked in `__swap` grids, so nothing shifts.
 */
export function WebVitalsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('VitalsPreview', isStatic && 'VitalsPreview--static')}>
            {/* Focus state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="vitals-preview-focus" className="VitalsPreview__checkbox" />

            <div className="VitalsPreview__tiles-card">
                <div className="VitalsPreview__head">
                    <span className="VitalsPreview__title">
                        <span className="VitalsPreview__live-dot" aria-hidden="true" />
                        Core Web Vitals · last 7 days
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="VitalsPreview__tiles">
                    <div className="VitalsPreview__tile">
                        <span className="VitalsPreview__tile-name">LCP</span>
                        <span className="VitalsPreview__tile-value">2.1 s</span>
                        <span className="VitalsPreview__tile-band VitalsPreview__tile-band--good">good</span>
                    </div>
                    <div className="VitalsPreview__tile">
                        <span className="VitalsPreview__tile-name">INP</span>
                        <span className="VitalsPreview__tile-value">180 ms</span>
                        <span className="VitalsPreview__tile-band VitalsPreview__tile-band--good">good</span>
                    </div>
                    <label htmlFor="vitals-preview-focus" className="VitalsPreview__tile VitalsPreview__tile--hero">
                        <span className="VitalsPreview__tile-name">CLS</span>
                        <span className="VitalsPreview__tile-value VitalsPreview__tile-value--poor">0.24</span>
                        <span className="VitalsPreview__tile-band VitalsPreview__tile-band--poor">poor</span>
                    </label>
                    <div className="VitalsPreview__tile">
                        <span className="VitalsPreview__tile-name">FCP</span>
                        <span className="VitalsPreview__tile-value">1.2 s</span>
                        <span className="VitalsPreview__tile-band VitalsPreview__tile-band--good">good</span>
                    </div>
                </div>
                <div className="VitalsPreview__hint VitalsPreview__swap">
                    <span className="VitalsPreview__when-idle">
                        Click the failing metric to find the pages behind it.
                    </span>
                    <span className="VitalsPreview__when-focused">
                        Two pages shift their layout on load. Click again to unfocus.
                    </span>
                </div>
            </div>

            <div className="VitalsPreview__pages">
                <div className="VitalsPreview__head">
                    <span className="VitalsPreview__title VitalsPreview__swap">
                        <span className="VitalsPreview__when-idle">Pages by traffic</span>
                        <span className="VitalsPreview__when-focused">Pages by CLS</span>
                    </span>
                    <span className="VitalsPreview__fresh VitalsPreview__when-focused">worst first</span>
                </div>
                <div className="VitalsPreview__rows">
                    <div className="VitalsPreview__row VitalsPreview__row--offender">
                        <span className="VitalsPreview__path">/pricing</span>
                        <span className="VitalsPreview__visits">8.1k visits</span>
                        <span className="VitalsPreview__score VitalsPreview__score--poor">CLS 0.41</span>
                    </div>
                    <div className="VitalsPreview__row VitalsPreview__row--offender">
                        <span className="VitalsPreview__path">/blog</span>
                        <span className="VitalsPreview__visits">5.4k visits</span>
                        <span className="VitalsPreview__score VitalsPreview__score--poor">CLS 0.29</span>
                    </div>
                    <div className="VitalsPreview__row">
                        <span className="VitalsPreview__path">/</span>
                        <span className="VitalsPreview__visits">21.9k visits</span>
                        <span className="VitalsPreview__score">CLS 0.05</span>
                    </div>
                    <div className="VitalsPreview__row">
                        <span className="VitalsPreview__path">/docs</span>
                        <span className="VitalsPreview__visits">12.2k visits</span>
                        <span className="VitalsPreview__score">CLS 0.02</span>
                    </div>
                </div>
            </div>
        </div>
    )
}
