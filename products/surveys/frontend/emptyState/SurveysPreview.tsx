import './SurveysPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

const NPS_SCORES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

/**
 * Example-data preview for the surveys empty state: the NPS popover a user sees
 * in-app, and the results it feeds. Clicking a score answers the survey - the
 * popover thanks the respondent, the response count ticks up, and the promoter
 * bar grows. One hidden checkbox drives it via `:checked ~` styles - no timers
 * or state, per the preview rules in the `building-product-empty-states` skill.
 * Answered/unanswered pairs are stacked in `__swap` grids, so nothing shifts.
 */
export function SurveysPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('SurveysPreview', isStatic && 'SurveysPreview--static')}>
            {/* Answered state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="surveys-preview-answer" className="SurveysPreview__checkbox" />

            <div className="SurveysPreview__app">
                <div className="SurveysPreview__chrome">
                    <span className="SurveysPreview__chrome-dot" />
                    <span className="SurveysPreview__chrome-dot" />
                    <span className="SurveysPreview__chrome-dot" />
                    <span className="SurveysPreview__url">yourapp.com/dashboard</span>
                </div>
                <div className="SurveysPreview__screen">
                    <div className="SurveysPreview__page" aria-hidden="true">
                        <span className="SurveysPreview__page-line" />
                        <span className="SurveysPreview__page-line SurveysPreview__page-line--short" />
                    </div>
                    <div className="SurveysPreview__popover">
                        <div className="SurveysPreview__popover-body SurveysPreview__swap">
                            <div className="SurveysPreview__question SurveysPreview__when-unanswered">
                                <span className="SurveysPreview__question-text">
                                    How likely are you to recommend us to a friend?
                                </span>
                                <span className="SurveysPreview__scale">
                                    {NPS_SCORES.map((score) =>
                                        score === 9 ? (
                                            <label
                                                key={score}
                                                htmlFor="surveys-preview-answer"
                                                className="SurveysPreview__score SurveysPreview__score--hero"
                                            >
                                                {score}
                                            </label>
                                        ) : (
                                            <span key={score} className="SurveysPreview__score">
                                                {score}
                                            </span>
                                        )
                                    )}
                                </span>
                                <span className="SurveysPreview__scale-labels">
                                    <span>Not likely</span>
                                    <span>Very likely</span>
                                </span>
                            </div>
                            <div className="SurveysPreview__thanks SurveysPreview__when-answered">
                                Thanks for your feedback!
                            </div>
                        </div>
                    </div>
                    <div className="SurveysPreview__hint SurveysPreview__swap">
                        <span className="SurveysPreview__when-unanswered">Answer the survey to see it land below.</span>
                        <span className="SurveysPreview__when-answered">
                            Counted, no code changes needed. Click 9 again to undo.
                        </span>
                    </div>
                </div>
            </div>

            <div className="SurveysPreview__results">
                <div className="SurveysPreview__head">
                    <span className="SurveysPreview__title">
                        <span className="SurveysPreview__live-dot" aria-hidden="true" />
                        NPS survey · results
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="SurveysPreview__stats">
                    <div className="SurveysPreview__stat">
                        <span className="SurveysPreview__stat-label">Responses</span>
                        <span className="SurveysPreview__stat-value SurveysPreview__swap">
                            <span className="SurveysPreview__when-unanswered">184</span>
                            <span className="SurveysPreview__when-answered SurveysPreview__stat-value--bumped">
                                185
                            </span>
                        </span>
                    </div>
                    <div className="SurveysPreview__stat">
                        <span className="SurveysPreview__stat-label">NPS score</span>
                        <span className="SurveysPreview__stat-value SurveysPreview__swap">
                            <span className="SurveysPreview__when-unanswered">42</span>
                            <span className="SurveysPreview__when-answered SurveysPreview__stat-value--bumped">43</span>
                        </span>
                    </div>
                </div>
                <div className="SurveysPreview__bar" aria-hidden="true">
                    <span className="SurveysPreview__bar-detractors" />
                    <span className="SurveysPreview__bar-passives" />
                    <span className="SurveysPreview__bar-promoters" />
                </div>
                <div className="SurveysPreview__legend">
                    <span className="SurveysPreview__legend-item SurveysPreview__legend-item--detractors">
                        Detractors
                    </span>
                    <span className="SurveysPreview__legend-item SurveysPreview__legend-item--passives">Passives</span>
                    <span className="SurveysPreview__legend-item SurveysPreview__legend-item--promoters">
                        Promoters
                    </span>
                </div>
                <div className="SurveysPreview__quote SurveysPreview__swap">
                    <span className="SurveysPreview__when-unanswered">
                        "Love the product, wish exports were faster."
                    </span>
                    <span className="SurveysPreview__when-answered SurveysPreview__quote--fresh">
                        Your response, just now: 9 · promoter
                    </span>
                </div>
            </div>
        </div>
    )
}
