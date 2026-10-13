import './NotebooksPreview.scss'

import { IconGraph, IconRewindPlay, IconToggle } from '@posthog/icons'

import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

// Hand-authored weekly sign-up series: a dip in the middle, then a recovery.
const LINE = 'M 0 14 L 14 12 L 28 15 L 42 27 L 56 25 L 70 18 L 84 12 L 100 8'

function areaPath(line: string): string {
    return `${line} L 100 40 L 0 40 Z`
}

/**
 * Example-data preview for the notebooks empty state: a notebook page mid-write,
 * with the block menu open where the cursor sits. Picking the trends block drops a
 * live insight into the page and the block count follows. One hidden checkbox drives
 * it via `:checked ~` styles - no timers or state, per the preview rules in the
 * `building-product-empty-states` skill. Both halves label the same checkbox, so the
 * inserted block clicks back out. Before/after pairs share a `__swap` grid cell and
 * crossfade, so the page never reflows.
 */
export function NotebooksPreview(): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()

    return (
        <div className={cn('NotebookPreview', isStatic && 'NotebookPreview--static')}>
            {/* Inserted state, before all cards so `:checked ~` can style them. */}
            <input type="checkbox" id="notebook-preview-insert" className="NotebookPreview__checkbox" />

            <div className="NotebookPreview__page">
                <div className="NotebookPreview__head">
                    <span className="NotebookPreview__title">Why sign-ups dipped in March</span>
                    <LemonTag size="small">example data</LemonTag>
                </div>

                <div className="NotebookPreview__doc">
                    <p className="NotebookPreview__para">
                        Sign-ups fell the week the new pricing page shipped.
                        <span className="NotebookPreview__caret" aria-hidden="true" />
                    </p>

                    <div className="NotebookPreview__slot NotebookPreview__swap">
                        <label
                            htmlFor="notebook-preview-insert"
                            className="NotebookPreview__menu NotebookPreview__when-before"
                        >
                            <span className="NotebookPreview__menu-head">Add a block</span>
                            <span className="NotebookPreview__menu-row NotebookPreview__menu-row--lead">
                                <IconGraph />
                                Trends insight
                            </span>
                            <span className="NotebookPreview__menu-row">
                                <IconRewindPlay />
                                Session replay
                            </span>
                            <span className="NotebookPreview__menu-row">
                                <IconToggle />
                                Feature flag
                            </span>
                        </label>

                        <label
                            htmlFor="notebook-preview-insert"
                            className="NotebookPreview__block NotebookPreview__when-after"
                        >
                            <span className="NotebookPreview__block-head">
                                <span className="NotebookPreview__block-title">Weekly sign-ups</span>
                                <span className="NotebookPreview__block-meta">Last 90 days</span>
                            </span>
                            <svg
                                className="NotebookPreview__spark-svg"
                                viewBox="0 0 100 40"
                                preserveAspectRatio="none"
                                aria-hidden="true"
                            >
                                <path className="NotebookPreview__spark-area" d={areaPath(LINE)} />
                                <path
                                    className="NotebookPreview__spark-line"
                                    d={LINE}
                                    vectorEffect="non-scaling-stroke"
                                />
                                <path
                                    className="NotebookPreview__spark-trace"
                                    d={LINE}
                                    pathLength={100}
                                    vectorEffect="non-scaling-stroke"
                                />
                            </svg>
                        </label>
                    </div>

                    <p className="NotebookPreview__para NotebookPreview__para--muted">
                        Retention held steady, so the drop is on acquisition.
                    </p>
                </div>
            </div>

            <div className="NotebookPreview__footer">
                <span className="NotebookPreview__count NotebookPreview__swap">
                    <span className="NotebookPreview__when-before">3 blocks</span>
                    <span className="NotebookPreview__when-after">4 blocks</span>
                </span>
                <span className="NotebookPreview__hint NotebookPreview__swap">
                    <span className="NotebookPreview__when-before">Pick a block to drop it into the page.</span>
                    <span className="NotebookPreview__when-after">
                        The block re-runs its query each time the page opens. Click it to remove.
                    </span>
                </span>
            </div>
        </div>
    )
}
