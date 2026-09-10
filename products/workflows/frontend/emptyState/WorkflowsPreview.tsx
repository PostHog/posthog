import './WorkflowsPreview.scss'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

/**
 * Example-data preview for the workflows empty state: a mini canvas and the
 * deliveries behind one of its branches. Clicking the condition node flips which
 * branch runs, and the stat card follows. One hidden checkbox drives it via
 * `:checked ~` styles - no timers or state, per the preview rules in the
 * `building-product-empty-states` skill. Branch pairs are stacked in `__swap`
 * grids, so nothing shifts.
 */
export function WorkflowsPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('WorkflowsPreview', isStatic && 'WorkflowsPreview--static')}>
            {/* Branch state, before both cards so `:checked ~` can style them. */}
            <input type="checkbox" id="workflows-preview-branch" className="WorkflowsPreview__checkbox" />

            <div className="WorkflowsPreview__canvas">
                <div className="WorkflowsPreview__head">
                    <span className="WorkflowsPreview__title">
                        <span className="WorkflowsPreview__live-dot" aria-hidden="true" />
                        Welcome journey
                    </span>
                    <LemonTag size="small">example data</LemonTag>
                </div>
                <div className="WorkflowsPreview__graph">
                    <div className="WorkflowsPreview__node">
                        <span className="WorkflowsPreview__node-kind">Trigger</span>
                        <span className="WorkflowsPreview__node-label">event: signed_up</span>
                    </div>
                    <span className="WorkflowsPreview__edge" aria-hidden="true">
                        <span className="WorkflowsPreview__edge-run" />
                    </span>
                    <div className="WorkflowsPreview__node">
                        <span className="WorkflowsPreview__node-kind">Wait</span>
                        <span className="WorkflowsPreview__node-label">1 day</span>
                    </div>
                    <span className="WorkflowsPreview__edge" aria-hidden="true" />
                    <label
                        htmlFor="workflows-preview-branch"
                        className="WorkflowsPreview__node WorkflowsPreview__node--hero"
                    >
                        <span className="WorkflowsPreview__node-kind">Condition</span>
                        <span className="WorkflowsPreview__node-label WorkflowsPreview__swap">
                            <span className="WorkflowsPreview__when-yes">opened welcome email? yes</span>
                            <span className="WorkflowsPreview__when-no">opened welcome email? no</span>
                        </span>
                    </label>
                    <span className="WorkflowsPreview__edge" aria-hidden="true" />
                    <div className="WorkflowsPreview__branches">
                        <div className="WorkflowsPreview__node WorkflowsPreview__node--branch WorkflowsPreview__branch-yes">
                            <span className="WorkflowsPreview__node-kind">Email</span>
                            <span className="WorkflowsPreview__node-label">Send tips</span>
                        </div>
                        <div className="WorkflowsPreview__node WorkflowsPreview__node--branch WorkflowsPreview__branch-no">
                            <span className="WorkflowsPreview__node-kind">Push</span>
                            <span className="WorkflowsPreview__node-label">Send reminder</span>
                        </div>
                    </div>
                </div>
                <div className="WorkflowsPreview__hint WorkflowsPreview__swap">
                    <span className="WorkflowsPreview__when-yes">Click the condition to follow the other branch.</span>
                    <span className="WorkflowsPreview__when-no">
                        Unopened emails get a push instead. Click to flip back.
                    </span>
                </div>
            </div>

            <div className="WorkflowsPreview__stat">
                <div className="WorkflowsPreview__spark-head">
                    <span className="WorkflowsPreview__spark-title WorkflowsPreview__swap">
                        <span className="WorkflowsPreview__when-yes">Tips email · deliveries, 7 days</span>
                        <span className="WorkflowsPreview__when-no">Reminder push · deliveries, 7 days</span>
                    </span>
                </div>
                <div className="WorkflowsPreview__spark-value">
                    <span className="WorkflowsPreview__swap">
                        <span className="WorkflowsPreview__when-yes">1,204</span>
                        <span className="WorkflowsPreview__when-no">618</span>
                    </span>
                    <span className="WorkflowsPreview__spark-sub WorkflowsPreview__swap">
                        <span className="WorkflowsPreview__when-yes">42% opened</span>
                        <span className="WorkflowsPreview__when-no">28% tapped</span>
                    </span>
                </div>
            </div>
        </div>
    )
}
