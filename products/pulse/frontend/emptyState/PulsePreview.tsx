import './PulsePreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored daily series behind each opportunity: a metric sliding down, and one climbing.
const LINE_DROPOFF = 'M 0 10 L 14 12 L 28 11 L 42 16 L 56 19 L 70 24 L 84 27 L 100 31'
const LINE_INVITES = 'M 0 30 L 14 29 L 28 26 L 42 24 L 56 18 L 70 15 L 84 11 L 100 8'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the Pulse empty state: a generated brief with two opportunities,
 * and the detail card for the selected one (summary, metric, suggested action). A hidden
 * radio pair drives the selection via `:checked ~` styles - no timers or state, per the
 * preview rules in the `building-product-empty-states` skill. Both details share one grid
 * cell and crossfade, so switching never moves the card.
 */
export function PulsePreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('PulsePreview', isStatic && 'PulsePreview--static')}>
            {/* Selected opportunity, before both cards so `:checked ~` can style them. */}
            <input
                type="radio"
                name="pulse-preview-opportunity"
                id="pulse-preview-dropoff"
                className="PulsePreview__radio PulsePreview__radio--dropoff"
                defaultChecked
            />
            <input
                type="radio"
                name="pulse-preview-opportunity"
                id="pulse-preview-invites"
                className="PulsePreview__radio PulsePreview__radio--invites"
            />

            <div className="PulsePreview__brief">
                <div className="PulsePreview__head">
                    <span className="PulsePreview__title">Weekly brief</span>
                    <span className="PulsePreview__period">Aug 25 to Sep 1</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="PulsePreview__section">
                    <span className="PulsePreview__section-title">What changed</span>
                    <p className="PulsePreview__text">
                        Signups held steady at 1,140 a week, but 31% fewer of them reached the dashboard within a day.
                        The drop starts with last Tuesday's release.
                    </p>
                    <div className="PulsePreview__citations">
                        <span className="PulsePreview__citation">Activation funnel</span>
                        <span className="PulsePreview__citation">Release 2.14</span>
                    </div>
                </div>

                <div className="PulsePreview__section">
                    <span className="PulsePreview__section-title">Opportunities</span>
                    <div className="PulsePreview__rows">
                        <label
                            htmlFor="pulse-preview-dropoff"
                            className="PulsePreview__row PulsePreview__row--dropoff PulsePreview__row--focus"
                        >
                            <span className="PulsePreview__dot" />
                            <span className="PulsePreview__row-title">Fix the day-one drop-off</span>
                            <span className="PulsePreview__delta PulsePreview__delta--down">-31%</span>
                        </label>
                        <label
                            htmlFor="pulse-preview-invites"
                            className="PulsePreview__row PulsePreview__row--invites PulsePreview__row--focus"
                        >
                            <span className="PulsePreview__dot" />
                            <span className="PulsePreview__row-title">Invites convert, nobody sends them</span>
                            <span className="PulsePreview__delta PulsePreview__delta--up">+2.4x</span>
                        </label>
                    </div>
                </div>
            </div>

            <div className="PulsePreview__detail">
                <div className="PulsePreview__swap">
                    <div className="PulsePreview__when-dropoff">
                        <div className="PulsePreview__spark-head">
                            <span className="PulsePreview__spark-title">Reached dashboard within a day</span>
                            <span className="PulsePreview__spark-caption">Baseline 62%</span>
                        </div>
                        <div className="PulsePreview__spark-value">
                            43%
                            <span className="PulsePreview__delta PulsePreview__delta--down">-31%</span>
                        </div>
                        <svg
                            className="PulsePreview__spark-svg"
                            viewBox="0 0 100 40"
                            preserveAspectRatio="none"
                            aria-hidden="true"
                        >
                            <path className="PulsePreview__spark-area" d={areaPath(LINE_DROPOFF)} />
                            <path
                                className="PulsePreview__spark-line"
                                d={LINE_DROPOFF}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="PulsePreview__spark-trace"
                                d={LINE_DROPOFF}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </svg>
                        <p className="PulsePreview__action">
                            <span className="PulsePreview__action-label">Suggested action</span>
                            Watch three replays of new users stuck on the empty dashboard, then ship a starter template.
                        </p>
                    </div>
                    <div className="PulsePreview__when-invites">
                        <div className="PulsePreview__spark-head">
                            <span className="PulsePreview__spark-title">Invited teammates who activate</span>
                            <span className="PulsePreview__spark-caption">Baseline 1x</span>
                        </div>
                        <div className="PulsePreview__spark-value">
                            2.4x
                            <span className="PulsePreview__delta PulsePreview__delta--up">vs solo signups</span>
                        </div>
                        <svg
                            className="PulsePreview__spark-svg"
                            viewBox="0 0 100 40"
                            preserveAspectRatio="none"
                            aria-hidden="true"
                        >
                            <path className="PulsePreview__spark-area" d={areaPath(LINE_INVITES)} />
                            <path
                                className="PulsePreview__spark-line"
                                d={LINE_INVITES}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="PulsePreview__spark-trace"
                                d={LINE_INVITES}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </svg>
                        <p className="PulsePreview__action">
                            <span className="PulsePreview__action-label">Suggested action</span>
                            Only 6% of new users invite anyone. Add an invite step to onboarding and test it with an
                            experiment.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    )
}
