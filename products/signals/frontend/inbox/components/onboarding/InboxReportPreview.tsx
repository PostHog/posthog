import './InboxReportPreview.scss'

import { useId, useRef } from 'react'

import {
    IconArrowLeft,
    IconCheckCircle,
    IconGraph,
    IconPullRequest,
    IconPulse,
    IconRefresh,
    IconRewindPlay,
    IconSupport,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { cn } from 'lib/utils/css-classes'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import { SignalReportPriorityBadge } from '../badges/SignalReportPriorityBadge'

// The sources a report draws on, in the order the setup flow offers them next.
const EVIDENCE: { label: string; icon: JSX.Element }[] = [
    { label: 'Session replay', icon: <IconRewindPlay /> },
    { label: 'Error tracking', icon: <IconWarning /> },
    { label: 'Product analytics', icon: <IconGraph /> },
    { label: 'Support', icon: <IconSupport /> },
]

const IMPACT_STAGES = [
    { stage: 'baseline', customers: '128', revenue: '-18%' },
    { stage: 'resolved', customers: '0', revenue: '0%' },
]

/** CSS stages keep this example local: playing the preview never starts an implementation. */
export function InboxReportPreview(_: { mode: ProductEmptyStateMode }): JSX.Element {
    const isStatic = inStorybook() || inStorybookTestRunner()
    const implementId = useId()
    const impactId = `${implementId}-impact`
    const inputRef = useRef<HTMLInputElement>(null)
    const impactRef = useRef<HTMLInputElement>(null)
    const cardRef = useRef<HTMLDivElement>(null)

    const resetImpact = (): void => {
        if (impactRef.current) {
            impactRef.current.checked = false
        }
    }

    const restartPreview = (): void => {
        resetImpact()
        if (inputRef.current) {
            inputRef.current.checked = false
        }
        for (const animation of cardRef.current?.getAnimations({ subtree: true }) ?? []) {
            if (animation instanceof CSSTransition) {
                animation.finish()
            } else {
                animation.currentTime = 0
                animation.play()
            }
        }
    }

    return (
        <div className={cn('InboxReportPreview', isStatic && 'InboxReportPreview--static')}>
            {/* A direct child of the root so `:checked ~` reaches the card. */}
            <input
                type="checkbox"
                id={implementId}
                ref={inputRef}
                aria-label="Show example fix"
                aria-controls={`${implementId}-card`}
                className="InboxReportPreview__checkbox"
                onChange={(event) => {
                    if (!event.target.checked) {
                        resetImpact()
                    }
                }}
            />

            <input
                type="checkbox"
                id={impactId}
                ref={impactRef}
                aria-label="Show example impact"
                aria-controls={`${implementId}-card`}
                className="InboxReportPreview__impact-checkbox"
            />

            <div className="absolute right-2 top-2 z-10">
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconRefresh />}
                    tooltip="Restart preview"
                    aria-label="Restart preview"
                    data-attr="inbox-report-preview-restart"
                    onClick={restartPreview}
                />
            </div>

            <div className="InboxReportPreview__card" id={`${implementId}-card`} ref={cardRef}>
                <div className="flex items-start gap-2 pr-8">
                    <SignalReportPriorityBadge priority="P0" />
                    <span className="InboxReportPreview__title">Trial users cannot upgrade to Pro</span>
                </div>

                {/* All stages occupy the same grid cell to reserve space without changing the card's height. */}
                <div className="InboxReportPreview__stages">
                    <div className="InboxReportPreview__report">
                        <section className="InboxReportPreview__section InboxReportPreview__context">
                            <h4 className="InboxReportPreview__heading">Problem</h4>
                            <p className="InboxReportPreview__text">
                                The billing page does not keep the selected plan. Trial users go back to the pricing
                                page and do not pay.
                            </p>
                        </section>

                        <section className="InboxReportPreview__section InboxReportPreview__context">
                            <h4 className="InboxReportPreview__heading">Impact</h4>
                            <div className="InboxReportPreview__metrics">
                                <div className="InboxReportPreview__metric">
                                    <span className="InboxReportPreview__metric-value">128</span>
                                    <span className="InboxReportPreview__metric-label">
                                        affected customers, last 7 days
                                    </span>
                                </div>
                                <div className="InboxReportPreview__metric">
                                    <span className="InboxReportPreview__metric-value text-danger">-18%</span>
                                    <span className="InboxReportPreview__metric-label">
                                        new subscription revenue, 7 days
                                    </span>
                                </div>
                            </div>
                        </section>

                        <section className="InboxReportPreview__section InboxReportPreview__context">
                            <h4 className="InboxReportPreview__heading">Evidence</h4>
                            <div className="InboxReportPreview__tags">
                                {EVIDENCE.map(({ label, icon }) => (
                                    <LemonTag key={label} size="small" icon={icon} className="InboxReportPreview__tag">
                                        {label}
                                    </LemonTag>
                                ))}
                            </div>
                        </section>

                        <section className="InboxReportPreview__section InboxReportPreview__solution">
                            <h4 className="InboxReportPreview__heading">Solution</h4>
                            <p className="InboxReportPreview__text">
                                Keep the selected plan when the billing page redirects.
                            </p>
                        </section>
                    </div>
                    <div className="InboxReportPreview__fix">
                        <section className="InboxReportPreview__section">
                            <h4 className="InboxReportPreview__heading">Proposed fix</h4>
                            <p className="InboxReportPreview__text">
                                Keep the selected plan when the billing page redirects.
                            </p>
                        </section>
                        <div className="InboxReportPreview__patch">
                            <div className="InboxReportPreview__patch-header">Example patch · billing.ts</div>
                            <pre className="InboxReportPreview__diff" aria-label="Example code change">
                                <code>
                                    <span>{'  function resumeUpgrade(plan) {'}</span>
                                    <del>- redirect('/pricing')</del>
                                    <ins>+ redirect(checkoutUrl(plan))</ins>
                                    <span>{'  }'}</span>
                                </code>
                            </pre>
                        </div>
                        <div className="InboxReportPreview__pull-request">
                            <div className="flex items-center gap-2">
                                <span className="InboxReportPreview__pr-state shrink-0">
                                    <IconPullRequest className="InboxReportPreview__pr-open text-success" />
                                    <IconCheckCircle className="InboxReportPreview__pr-merged text-purple" />
                                </span>
                                <h4 className="InboxReportPreview__heading mb-0">Pull request</h4>
                                <div className="InboxReportPreview__pr-state">
                                    <LemonTag type="success" size="small" className="InboxReportPreview__pr-open">
                                        Open
                                    </LemonTag>
                                    <LemonTag type="completion" size="small" className="InboxReportPreview__pr-merged">
                                        PR merged
                                    </LemonTag>
                                </div>
                            </div>
                            <p className="InboxReportPreview__pr-title">fix(billing): preserve the selected plan</p>
                            <div className="InboxReportPreview__pr-state">
                                <p className="InboxReportPreview__text text-secondary InboxReportPreview__pr-open">
                                    Ready for your review.
                                </p>
                                <p className="InboxReportPreview__text text-secondary InboxReportPreview__pr-merged">
                                    Merged and deployed.
                                </p>
                            </div>
                        </div>
                    </div>
                    <div className="InboxReportPreview__monitoring">
                        <section className="InboxReportPreview__section InboxReportPreview__monitoring-details">
                            <h4 className="InboxReportPreview__heading">Monitoring impact</h4>
                            <div className="InboxReportPreview__impact-values">
                                {IMPACT_STAGES.map(({ stage, customers, revenue }) => (
                                    <div
                                        key={stage}
                                        className={`InboxReportPreview__impact-frame InboxReportPreview__impact-frame--${stage}`}
                                    >
                                        <div className="InboxReportPreview__metrics">
                                            <div className="InboxReportPreview__metric">
                                                <span
                                                    className={cn(
                                                        'InboxReportPreview__metric-value',
                                                        stage === 'resolved' && 'text-success'
                                                    )}
                                                >
                                                    {customers}
                                                </span>
                                                <span className="InboxReportPreview__metric-label">
                                                    affected customers
                                                </span>
                                            </div>
                                            <div className="InboxReportPreview__metric">
                                                <span
                                                    className={cn(
                                                        'InboxReportPreview__metric-value',
                                                        stage === 'resolved' ? 'text-success' : 'text-danger'
                                                    )}
                                                >
                                                    {revenue}
                                                </span>
                                                <span className="InboxReportPreview__metric-label">revenue impact</span>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </section>
                        <figure className="InboxReportPreview__impact-chart">
                            <figcaption className="InboxReportPreview__chart-caption">
                                Affected customers per day · example
                            </figcaption>
                            <svg
                                viewBox="0 0 320 116"
                                role="img"
                                aria-label="Example affected customers stay near 128 before the PR merges, then drop to zero shortly after merge when the fix is deployed and remain there."
                            >
                                <line x1="34" y1="32" x2="304" y2="32" className="InboxReportPreview__chart-grid" />
                                <line x1="34" y1="92" x2="304" y2="92" className="InboxReportPreview__chart-grid" />
                                <text x="25" y="35" textAnchor="end">
                                    128
                                </text>
                                <text x="25" y="95" textAnchor="end">
                                    0
                                </text>
                                <g className="InboxReportPreview__merge-event">
                                    <line
                                        x1="130"
                                        y1="20"
                                        x2="130"
                                        y2="96"
                                        className="InboxReportPreview__merge-marker"
                                    />
                                    <text
                                        x="130"
                                        y="12"
                                        textAnchor="middle"
                                        className="InboxReportPreview__merge-label"
                                    >
                                        PR merged
                                    </text>
                                </g>
                                <path
                                    d="M34 32 L58 29 L82 34 L106 31 L130 32"
                                    className="InboxReportPreview__chart-before"
                                />
                                <path
                                    d="M130 32 H150 V92 H304"
                                    pathLength="1"
                                    className="InboxReportPreview__chart-after"
                                />
                                <circle cx="304" cy="92" r="3" className="InboxReportPreview__chart-zero" />
                                <text x="34" y="112">
                                    Before merge
                                </text>
                                <text x="304" y="112" textAnchor="end">
                                    After merge
                                </text>
                            </svg>
                        </figure>
                        <div className="InboxReportPreview__outcome-status">
                            <p className="InboxReportPreview__watching">
                                <IconPulse className="shrink-0" />
                                Monitoring for recurring failures
                            </p>
                            <p className="InboxReportPreview__resolved text-success">
                                <IconCheckCircle className="shrink-0" />
                                No new failed upgrades observed
                            </p>
                        </div>
                    </div>
                </div>
                <div className="InboxReportPreview__actions">
                    <label htmlFor={implementId} className="InboxReportPreview__implement">
                        <IconPullRequest />
                        Implement
                    </label>
                    <div className="InboxReportPreview__manual-actions">
                        <label htmlFor={implementId} className="InboxReportPreview__back">
                            <IconArrowLeft />
                            Back to report
                        </label>
                        <label htmlFor={impactId} className="InboxReportPreview__see-impact">
                            <span className="InboxReportPreview__see-impact-label">See impact</span>
                            <span className="InboxReportPreview__back-to-fix-label">Back to fix</span>
                        </label>
                    </div>
                </div>
            </div>
            <p className="mt-3 mb-0 text-xs">
                <Link to="https://posthog.com/docs/self-driving/from-our-inbox" target="_blank">
                    See reports generated for PostHog
                </Link>
            </p>
        </div>
    )
}
