import './EngineeringAnalyticsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored weekly series of median time from open to merge, in hours, trending down.
const LINE = 'M 0 9 L 14 12 L 28 10 L 42 16 L 56 18 L 70 23 L 84 26 L 100 30'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the engineering analytics empty state: the pull request list next
 * to the CI runs of the selected pull request, plus the team's time-to-merge trend. A hidden
 * radio pair drives the selection via `:checked ~` styles - no timers or state, per the
 * preview rules in the `building-product-empty-states` skill. Both run lists share one grid
 * cell and crossfade, so switching never moves the card.
 */
export function EngineeringAnalyticsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('EngAnalyticsPreview', isStatic && 'EngAnalyticsPreview--static')}>
            {/* Selected pull request, before both cards so `:checked ~` can style them. */}
            <input
                type="radio"
                name="eng-analytics-preview-pr"
                id="eng-analytics-preview-pr-green"
                className="EngAnalyticsPreview__radio EngAnalyticsPreview__radio--green"
                defaultChecked
            />
            <input
                type="radio"
                name="eng-analytics-preview-pr"
                id="eng-analytics-preview-pr-red"
                className="EngAnalyticsPreview__radio EngAnalyticsPreview__radio--red"
            />

            <div className="EngAnalyticsPreview__panel">
                <div className="EngAnalyticsPreview__head">
                    <span className="EngAnalyticsPreview__title">Pull requests</span>
                    <span className="EngAnalyticsPreview__repo">acme/web</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="EngAnalyticsPreview__rows">
                    <label
                        htmlFor="eng-analytics-preview-pr-green"
                        className="EngAnalyticsPreview__row EngAnalyticsPreview__row--green EngAnalyticsPreview__row--focus"
                    >
                        <span className="EngAnalyticsPreview__ci EngAnalyticsPreview__ci--pass" />
                        <span className="EngAnalyticsPreview__pr">
                            <span className="EngAnalyticsPreview__pr-title">
                                feat(checkout): remember the last payment method
                            </span>
                            <span className="EngAnalyticsPreview__pr-meta">#4821 by mara, merged in 6h 12m</span>
                        </span>
                        <span className="EngAnalyticsPreview__pill EngAnalyticsPreview__pill--pass">Merged</span>
                    </label>

                    <label
                        htmlFor="eng-analytics-preview-pr-red"
                        className="EngAnalyticsPreview__row EngAnalyticsPreview__row--red EngAnalyticsPreview__row--focus"
                    >
                        <span className="EngAnalyticsPreview__ci EngAnalyticsPreview__ci--fail" />
                        <span className="EngAnalyticsPreview__pr">
                            <span className="EngAnalyticsPreview__pr-title">
                                fix(api): retry warehouse reads on timeout
                            </span>
                            <span className="EngAnalyticsPreview__pr-meta">#4819 by theo, open for 2d 4h</span>
                        </span>
                        <span className="EngAnalyticsPreview__pill EngAnalyticsPreview__pill--fail">CI failing</span>
                    </label>

                    <div className="EngAnalyticsPreview__row">
                        <span className="EngAnalyticsPreview__ci EngAnalyticsPreview__ci--running" />
                        <span className="EngAnalyticsPreview__pr">
                            <span className="EngAnalyticsPreview__pr-title">
                                chore(deps): bump the frontend toolchain
                            </span>
                            <span className="EngAnalyticsPreview__pr-meta">#4823 by bot, CI running</span>
                        </span>
                        <span className="EngAnalyticsPreview__pill">Open</span>
                    </div>
                </div>
            </div>

            <div className="EngAnalyticsPreview__bottom">
                <div className="EngAnalyticsPreview__runs">
                    <div className="EngAnalyticsPreview__runs-head EngAnalyticsPreview__swap">
                        <span className="EngAnalyticsPreview__when-green">Workflow runs on #4821</span>
                        <span className="EngAnalyticsPreview__when-red">Workflow runs on #4819</span>
                    </div>
                    <div className="EngAnalyticsPreview__swap">
                        <div className="EngAnalyticsPreview__when-green EngAnalyticsPreview__jobs">
                            <span className="EngAnalyticsPreview__job">
                                <span className="EngAnalyticsPreview__job-name">Lint</span>
                                <span className="EngAnalyticsPreview__bar">
                                    <span className="EngAnalyticsPreview__bar-fill EngAnalyticsPreview__bar-fill--pass EngAnalyticsPreview__bar-fill--w20" />
                                </span>
                                <span className="EngAnalyticsPreview__job-time">1m 40s</span>
                            </span>
                            <span className="EngAnalyticsPreview__job">
                                <span className="EngAnalyticsPreview__job-name">Unit tests</span>
                                <span className="EngAnalyticsPreview__bar">
                                    <span className="EngAnalyticsPreview__bar-fill EngAnalyticsPreview__bar-fill--pass EngAnalyticsPreview__bar-fill--w65" />
                                </span>
                                <span className="EngAnalyticsPreview__job-time">6m 05s</span>
                            </span>
                            <span className="EngAnalyticsPreview__job">
                                <span className="EngAnalyticsPreview__job-name">E2E</span>
                                <span className="EngAnalyticsPreview__bar">
                                    <span className="EngAnalyticsPreview__bar-fill EngAnalyticsPreview__bar-fill--pass EngAnalyticsPreview__bar-fill--w90" />
                                </span>
                                <span className="EngAnalyticsPreview__job-time">8m 52s</span>
                            </span>
                        </div>
                        <div className="EngAnalyticsPreview__when-red EngAnalyticsPreview__jobs">
                            <span className="EngAnalyticsPreview__job">
                                <span className="EngAnalyticsPreview__job-name">Lint</span>
                                <span className="EngAnalyticsPreview__bar">
                                    <span className="EngAnalyticsPreview__bar-fill EngAnalyticsPreview__bar-fill--pass EngAnalyticsPreview__bar-fill--w20" />
                                </span>
                                <span className="EngAnalyticsPreview__job-time">1m 38s</span>
                            </span>
                            <span className="EngAnalyticsPreview__job">
                                <span className="EngAnalyticsPreview__job-name">Unit tests</span>
                                <span className="EngAnalyticsPreview__bar">
                                    <span className="EngAnalyticsPreview__bar-fill EngAnalyticsPreview__bar-fill--fail EngAnalyticsPreview__bar-fill--w45" />
                                </span>
                                <span className="EngAnalyticsPreview__job-time">failed, 3rd retry</span>
                            </span>
                            <span className="EngAnalyticsPreview__job">
                                <span className="EngAnalyticsPreview__job-name">E2E</span>
                                <span className="EngAnalyticsPreview__bar">
                                    <span className="EngAnalyticsPreview__bar-fill EngAnalyticsPreview__bar-fill--skip EngAnalyticsPreview__bar-fill--w10" />
                                </span>
                                <span className="EngAnalyticsPreview__job-time">skipped</span>
                            </span>
                        </div>
                    </div>
                </div>

                <div className="EngAnalyticsPreview__stat">
                    <div className="EngAnalyticsPreview__spark-head">
                        <span className="EngAnalyticsPreview__spark-title">Median open to merge</span>
                        <span className="EngAnalyticsPreview__spark-caption">8 weeks</span>
                    </div>
                    <div className="EngAnalyticsPreview__spark-value">
                        9h 40m
                        <span className="EngAnalyticsPreview__pill EngAnalyticsPreview__pill--pass">-31%</span>
                    </div>
                    <svg
                        className="EngAnalyticsPreview__spark-svg"
                        viewBox="0 0 100 40"
                        preserveAspectRatio="none"
                        aria-hidden="true"
                    >
                        <path className="EngAnalyticsPreview__spark-area" d={areaPath(LINE)} />
                        <path className="EngAnalyticsPreview__spark-line" d={LINE} vectorEffect="non-scaling-stroke" />
                        <path
                            className="EngAnalyticsPreview__spark-trace"
                            d={LINE}
                            pathLength={100}
                            vectorEffect="non-scaling-stroke"
                        />
                    </svg>
                    <span className="EngAnalyticsPreview__footer">
                        CI pass rate 94%. Unit tests flaky on 3 of 41 runs.
                    </span>
                </div>
            </div>
        </div>
    )
}
