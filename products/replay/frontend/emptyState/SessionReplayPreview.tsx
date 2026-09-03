import './SessionReplayPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the session replay empty state: a recordings list and
 * the player. Clicking the top recording plays it - the cursor moves through the
 * mini app, the click ripples, and the timeline advances. One hidden checkbox
 * drives it via `:checked ~` styles; the playback motion is CSS keyframes that
 * only run while checked, per the preview rules in the
 * `building-product-empty-states` skill. Playing/paused pairs are stacked in
 * `__swap` grids, so nothing shifts.
 */
export function SessionReplayPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('ReplayPreview', isStatic && 'ReplayPreview--static')}>
            {/* Playing state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="replay-preview-play" className="ReplayPreview__checkbox" />

            <div className="ReplayPreview__list">
                <div className="ReplayPreview__head">
                    <span className="ReplayPreview__title">
                        <span className="ReplayPreview__rec-dot" aria-hidden="true" />
                        Recordings
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="ReplayPreview__rows">
                    <label htmlFor="replay-preview-play" className="ReplayPreview__row ReplayPreview__row--hero">
                        <span className="ReplayPreview__person">Mia K.</span>
                        <span className="ReplayPreview__meta">checkout flow · 12 clicks</span>
                        <span className="ReplayPreview__duration ReplayPreview__swap">
                            <span className="ReplayPreview__when-paused">4:12</span>
                            <span className="ReplayPreview__now-playing ReplayPreview__when-playing">playing</span>
                        </span>
                    </label>
                    <div className="ReplayPreview__row">
                        <span className="ReplayPreview__person">Anonymous user</span>
                        <span className="ReplayPreview__meta">pricing page · 3 clicks</span>
                        <span className="ReplayPreview__duration">1:03</span>
                    </div>
                    <div className="ReplayPreview__row">
                        <span className="ReplayPreview__person">Sam T.</span>
                        <span className="ReplayPreview__meta">dashboard · 41 clicks</span>
                        <span className="ReplayPreview__duration">12:40</span>
                    </div>
                </div>
                <div className="ReplayPreview__hint ReplayPreview__swap">
                    <span className="ReplayPreview__when-paused">Click a recording to watch the session.</span>
                    <span className="ReplayPreview__when-playing">
                        Every click, scroll, and console log, replayed. Click again to pause.
                    </span>
                </div>
            </div>

            <div className="ReplayPreview__player">
                <div className="ReplayPreview__screen">
                    {/* The recorded app: a wireframe page the cursor travels through while playing. */}
                    <div className="ReplayPreview__wire" aria-hidden="true">
                        <span className="ReplayPreview__wire-nav" />
                        <span className="ReplayPreview__wire-line" />
                        <span className="ReplayPreview__wire-line ReplayPreview__wire-line--short" />
                        <span className="ReplayPreview__wire-button" />
                    </div>
                    <span className="ReplayPreview__cursor" aria-hidden="true" />
                    <div className="ReplayPreview__overlay ReplayPreview__when-paused" aria-hidden="true">
                        <span className="ReplayPreview__overlay-play">▶</span>
                    </div>
                </div>
                <div className="ReplayPreview__controls">
                    <span className="ReplayPreview__play-glyph ReplayPreview__swap" aria-hidden="true">
                        <span className="ReplayPreview__when-paused">▶</span>
                        <span className="ReplayPreview__when-playing">❚❚</span>
                    </span>
                    <span className="ReplayPreview__timeline" aria-hidden="true">
                        <span className="ReplayPreview__timeline-activity" />
                        <span className="ReplayPreview__timeline-progress" />
                    </span>
                    <span className="ReplayPreview__time ReplayPreview__swap">
                        <span className="ReplayPreview__when-paused">0:00 / 4:12</span>
                        <span className="ReplayPreview__when-playing">· / 4:12</span>
                    </span>
                </div>
            </div>
        </div>
    )
}
