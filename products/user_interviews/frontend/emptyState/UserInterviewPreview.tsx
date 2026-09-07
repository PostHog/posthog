import './UserInterviewPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored rising response series for the stat card sparkline, one per topic.
const LINE_A = 'M 0 34 L 10 32 L 20 32.6 L 30 29 L 40 29.8 L 50 26 L 60 26.8 L 70 22.5 L 80 21 L 90 17.5 L 100 15'
const LINE_B = 'M 0 35 L 10 34 L 20 34.4 L 30 32 L 40 32.6 L 50 30 L 60 30.6 L 70 28 L 80 27 L 90 24.5 L 100 23'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the user research empty state: the topic list wired to a
 * live interview transcript and a responses stat card, so picking a topic swaps which
 * interview and response count show. The whole interaction is two hidden radios
 * driving `:checked ~` styles - no timers or state, per the preview rules in the
 * `building-product-empty-states` skill. Topic variants are stacked in `__swap` grids
 * and crossfaded, so switching never changes the layout's size.
 */
export function UserInterviewPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('ResearchPreview', isStatic && 'ResearchPreview--static')}>
            {/* Topic selection, before all three cards so `:checked ~` can style them. */}
            <input
                type="radio"
                name="research-preview-topic"
                id="research-preview-a"
                defaultChecked
                className="ResearchPreview__radio"
            />
            <input
                type="radio"
                name="research-preview-topic"
                id="research-preview-b"
                className="ResearchPreview__radio"
            />

            <div className="ResearchPreview__panel">
                <div className="ResearchPreview__head">
                    <span className="ResearchPreview__title">Research topics</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="ResearchPreview__rows">
                    <label htmlFor="research-preview-a" className="ResearchPreview__row ResearchPreview__row--a">
                        <span className="ResearchPreview__vradio ResearchPreview__vradio--a" aria-hidden="true" />
                        <span className="ResearchPreview__topic">Onboarding friction</span>
                        <span className="ResearchPreview__targeting">12 emails + 4 IDs</span>
                        <span className="ResearchPreview__questions">5 questions</span>
                    </label>
                    <label htmlFor="research-preview-b" className="ResearchPreview__row ResearchPreview__row--b">
                        <span className="ResearchPreview__vradio ResearchPreview__vradio--b" aria-hidden="true" />
                        <span className="ResearchPreview__topic">Churn reasons</span>
                        <span className="ResearchPreview__targeting">26 emails</span>
                        <span className="ResearchPreview__questions">4 questions</span>
                    </label>
                </div>

                <div className="ResearchPreview__hint">Pick a topic to read one of its interviews.</div>
            </div>

            <div className="ResearchPreview__interview">
                <div className="ResearchPreview__interview-head">
                    <span className="ResearchPreview__live">
                        <span className="ResearchPreview__live-dot" aria-hidden="true" />
                        Interview in progress
                    </span>
                    <span className="ResearchPreview__swap ResearchPreview__who">
                        <span className="ResearchPreview__on-a">rafa@acme.dev</span>
                        <span className="ResearchPreview__on-b">lily@umbrella.co</span>
                    </span>
                </div>

                <div className="ResearchPreview__transcript">
                    <div className="ResearchPreview__msg ResearchPreview__msg--ai">
                        <span className="ResearchPreview__speaker">AI interviewer</span>
                        <span className="ResearchPreview__swap ResearchPreview__bubble ResearchPreview__bubble--ai">
                            <span className="ResearchPreview__on-a">
                                What slowed you down when you first set up tracking?
                            </span>
                            <span className="ResearchPreview__on-b">What made you decide to cancel your plan?</span>
                        </span>
                    </div>
                    <div className="ResearchPreview__msg ResearchPreview__msg--user">
                        <span className="ResearchPreview__speaker">Participant</span>
                        <span className="ResearchPreview__swap ResearchPreview__bubble ResearchPreview__bubble--user">
                            <span className="ResearchPreview__on-a">
                                I couldn't tell which steps were required, so I skipped the install and got stuck.
                            </span>
                            <span className="ResearchPreview__on-b">
                                Nothing was wrong. We only needed it for one launch, and the project ended.
                            </span>
                        </span>
                    </div>
                </div>
            </div>

            <div className="ResearchPreview__spark">
                <div className="ResearchPreview__spark-head">
                    <span className="ResearchPreview__swap ResearchPreview__spark-title">
                        <span className="ResearchPreview__on-a">Responses · Onboarding friction</span>
                        <span className="ResearchPreview__on-b">Responses · Churn reasons</span>
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="ResearchPreview__spark-value">
                    <span className="ResearchPreview__swap">
                        <span className="ResearchPreview__on-a">18</span>
                        <span className="ResearchPreview__on-b">11</span>
                    </span>
                    <span className="ResearchPreview__spark-note">completed interviews</span>
                </div>

                <div className="ResearchPreview__spark-chart">
                    <svg
                        className="ResearchPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <g className="ResearchPreview__spark-g ResearchPreview__on-a">
                            <path className="ResearchPreview__spark-area" d={areaPath(LINE_A)} />
                            <path
                                className="ResearchPreview__spark-line"
                                d={LINE_A}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="ResearchPreview__spark-trace"
                                d={LINE_A}
                                pathLength={100}
                                vectorEffect="non-scaling-stroke"
                            />
                        </g>
                        <g className="ResearchPreview__spark-g ResearchPreview__on-b">
                            <path className="ResearchPreview__spark-area" d={areaPath(LINE_B)} />
                            <path
                                className="ResearchPreview__spark-line"
                                d={LINE_B}
                                vectorEffect="non-scaling-stroke"
                            />
                            <path
                                className="ResearchPreview__spark-trace"
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
