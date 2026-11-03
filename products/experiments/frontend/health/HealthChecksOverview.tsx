import { useActions } from 'kea'
import { useState } from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { HealthCheckDetail } from './HealthCheckDetail'
import { HealthCheckList } from './HealthCheckList'
import { HealthChecksSummary } from './HealthChecksSummary'
import { HealthChecksSummaryDetail } from './HealthChecksSummaryDetail'
import { HealthFindingDetail } from './HealthFindingDetail'
import { HealthFindingListItem } from './HealthFindingListItem'
import { type HealthPanelCheck, listedHealthChecks } from './healthPanelChecks'
import { type HealthPanelFinding, healthIssues } from './healthPanelFindings'
import { type HealthPanelSelection, healthFindingKey, resolveHealthPanelSelection } from './healthPanelSelection'

export function HealthChecksOverview({
    checks,
    findings,
    isDraft,
    exposureChecksMissing,
    onFindingActedOn,
}: {
    checks: HealthPanelCheck[]
    /** Issues first, as `healthPanelFindings` sorts them. */
    findings: HealthPanelFinding[]
    isDraft: boolean
    exposureChecksMissing: boolean
    onFindingActedOn?: () => void
}): JSX.Element {
    const [pickedSelection, setPickedSelection] = useState<HealthPanelSelection | null>(null)
    // A narrow container shows the list or the detail, not both. Wide containers ignore this.
    const [isDetailOpenWhenNarrow, setIsDetailOpenWhenNarrow] = useState(false)
    const { reportHealthCheckExpanded } = useActions(experimentLogic)
    const listedChecks = listedHealthChecks(checks)
    const issueCount = healthIssues(findings).length
    const selection = resolveHealthPanelSelection(pickedSelection, findings, listedChecks)

    const select = (next: HealthPanelSelection): void => {
        setPickedSelection(next)
        setIsDetailOpenWhenNarrow(true)
    }

    return (
        <div className="@container/health-checks w-full" data-attr="experiment-health-overview">
            <div className="flex flex-col @min-[48rem]/health-checks:flex-row">
                <nav
                    aria-label="Health checks"
                    className={cn(
                        'flex-col @min-[48rem]/health-checks:flex @min-[48rem]/health-checks:w-80 @min-[48rem]/health-checks:shrink-0 @min-[48rem]/health-checks:border-r',
                        isDetailOpenWhenNarrow ? 'hidden' : 'flex'
                    )}
                >
                    <div className="flex flex-col gap-1 px-3 py-2">
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold">Health checks</span>
                            <LemonTag type="completion">Beta</LemonTag>
                        </div>
                        <HealthChecksSummary checks={checks} issueCount={issueCount} isDraft={isDraft} />
                    </div>
                    {findings.length > 0 && (
                        // A note mounts, and so reports as shown, only when the reader opens the health tab. An issue
                        // reports once per load, from the header chip or from here, whichever shows it first.
                        <ul className="m-0 list-none flex flex-col gap-0.5 border-t px-1 py-2">
                            {findings.map((finding) => {
                                const key = healthFindingKey(finding)
                                return (
                                    <HealthFindingListItem
                                        key={key}
                                        finding={finding}
                                        isSelected={selection.kind === 'finding' && selection.key === key}
                                        onSelect={() => select({ kind: 'finding', key })}
                                    />
                                )
                            })}
                        </ul>
                    )}
                    {(listedChecks.length > 0 || exposureChecksMissing) && (
                        <div className="border-t">
                            <HealthCheckList
                                checks={listedChecks}
                                exposureChecksMissing={exposureChecksMissing}
                                selectedKey={selection.kind === 'check' ? selection.key : null}
                                onSelect={(check) => {
                                    if (!(selection.kind === 'check' && selection.key === check.key)) {
                                        reportHealthCheckExpanded(check)
                                    }
                                    select({ kind: 'check', key: check.key })
                                }}
                            />
                        </div>
                    )}
                </nav>
                <section
                    aria-label="Health check details"
                    className={cn(
                        'flex-1 min-w-0 flex-col gap-3 px-4 py-3 @min-[48rem]/health-checks:flex',
                        isDetailOpenWhenNarrow ? 'flex' : 'hidden'
                    )}
                >
                    <LemonButton
                        size="small"
                        icon={<IconChevronLeft />}
                        className="self-start @min-[48rem]/health-checks:hidden"
                        onClick={() => setIsDetailOpenWhenNarrow(false)}
                        data-attr="experiment-health-back-to-list"
                    >
                        All checks
                    </LemonButton>
                    {selection.kind === 'finding' ? (
                        <HealthFindingDetail finding={selection.finding} onActedOn={onFindingActedOn} />
                    ) : selection.kind === 'check' ? (
                        <HealthCheckDetail check={selection.check} />
                    ) : (
                        <HealthChecksSummaryDetail checks={checks} issueCount={issueCount} />
                    )}
                </section>
            </div>
        </div>
    )
}
