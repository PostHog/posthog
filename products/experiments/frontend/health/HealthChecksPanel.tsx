import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { groupsModel } from '~/models/groupsModel'
import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import type { ExperimentHealthSetupApi } from '../generated/api.schemas'
import { exposureAnswerComputedAt } from './exposureHealth'
import { HealthCheckDetail } from './HealthCheckDetail'
import { HealthCheckList } from './HealthCheckList'
import { HealthChecksCoverageNote } from './HealthChecksCoverageNote'
import { HealthFindingDetail } from './HealthFindingDetail'
import { HealthFindingListItem } from './HealthFindingListItem'
import { HealthOverviewDetail } from './HealthOverviewDetail'
import { type HealthPanelCheck, listedHealthChecks } from './healthPanelChecks'
import { type HealthPanelFinding, healthIssues } from './healthPanelFindings'
import { type HealthPanelSelection, healthFindingKey, resolveHealthPanelSelection } from './healthPanelSelection'

export function HealthChecksPanel({
    checks,
    findings,
    setup,
    exposures,
    isDraft,
    exposureChecksMissing,
    onFindingActedOn,
}: {
    checks: HealthPanelCheck[]
    /** Issues first, as `healthPanelFindings` sorts them. */
    findings: HealthPanelFinding[]
    setup: ExperimentHealthSetupApi | null
    /** The exposure answer that the exposure checks come from. Null for a draft and before it loads. */
    exposures: ExperimentExposureQueryResponse | null
    isDraft: boolean
    exposureChecksMissing: boolean
    onFindingActedOn?: () => void
}): JSX.Element {
    const [pickedSelection, setPickedSelection] = useState<HealthPanelSelection | null>(null)
    // A narrow container shows the list or the detail, not both. Wide containers ignore this.
    const [isDetailOpenWhenNarrow, setIsDetailOpenWhenNarrow] = useState(false)
    const { experiment } = useValues(experimentLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { reportHealthCheckExpanded, reportHealthOverviewOpened } = useActions(experimentLogic)
    const listedChecks = listedHealthChecks(checks)
    const findingGroups = [
        { label: 'Issues', findings: healthIssues(findings) },
        { label: 'Notes', findings: findings.filter(({ severity }) => severity === 'info') },
    ].filter((group) => group.findings.length > 0)
    const selection = resolveHealthPanelSelection(pickedSelection, findings, listedChecks)
    const units = aggregationLabel(experiment.feature_flag?.filters?.aggregation_group_type_index, true).plural
    const exposureCheckKeys = new Set<string>(exposures?.health_checks?.map(({ key }) => key))
    const exposureCheckedAt = exposureAnswerComputedAt(exposures)
    // The checks of the experiment run on each load, so only the exposure checks say when they ran.
    const checkedAt = (key: HealthPanelCheck['key']): string | null =>
        exposureCheckKeys.has(key) ? exposureCheckedAt : null

    const detailRef = useRef<HTMLElement>(null)

    // Returns whether the pick puts a detail on screen, which is what reports it as opened. The overview shows
    // without a click, but only beside the list: a narrow container hides the detail behind the list, so there a
    // click opens even the item that is already picked. Only the container query knows the width, so ask the page.
    const select = (next: HealthPanelSelection, isSelected: boolean): boolean => {
        const opensDetail = !isSelected || !detailRef.current || getComputedStyle(detailRef.current).display === 'none'
        setPickedSelection(next)
        setIsDetailOpenWhenNarrow(true)
        return opensDetail
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
                    {/* An inner column, so the nav border keeps the panel height. Sticky offsets start inside the `p-4`
                        of `#main-content`, so the height leaves out that padding as well as the header. */}
                    <div className="flex flex-col @min-[48rem]/health-checks:sticky @min-[48rem]/health-checks:top-(--scene-layout-header-height) @min-[48rem]/health-checks:max-h-[calc(var(--scene-layout-rect-height,100dvh)_-_var(--scene-layout-header-height)_-_var(--spacing)*4)] @min-[48rem]/health-checks:overflow-y-auto">
                        <div className="p-2">
                            <LemonButton
                                fullWidth
                                active={selection.kind === 'overview'}
                                onClick={() => {
                                    if (select({ kind: 'overview' }, selection.kind === 'overview')) {
                                        reportHealthOverviewOpened()
                                    }
                                }}
                                aria-current={selection.kind === 'overview' ? 'true' : undefined}
                                // pinned: `data-attr` value, so renaming it breaks autocapture insights
                                data-attr="experiment-health-summary-header"
                            >
                                <span className="flex flex-col gap-1 py-1.5 text-left font-normal">
                                    <span className="flex items-center gap-2">
                                        <span className="text-sm font-semibold">Health checks</span>
                                        <LemonTag type="completion">Beta</LemonTag>
                                    </span>
                                    <HealthChecksCoverageNote isDraft={isDraft} />
                                </span>
                            </LemonButton>
                        </div>
                        {findingGroups.length > 0 && (
                            // A note mounts, and so reports as shown, only when the reader opens the health tab. An issue
                            // reports once per load, from the header chip or from here, whichever shows it first.
                            <div className="flex flex-col gap-5 border-t px-4 py-3">
                                {findingGroups.map((group) => (
                                    <div key={group.label} className="flex flex-col gap-1.5">
                                        <span className="text-xs font-semibold text-secondary">{group.label}</span>
                                        <ul className="-mx-2 m-0 p-0 list-none flex flex-col gap-1">
                                            {group.findings.map((finding) => {
                                                const key = healthFindingKey(finding)
                                                const isSelected = selection.kind === 'finding' && selection.key === key
                                                return (
                                                    <HealthFindingListItem
                                                        key={key}
                                                        finding={finding}
                                                        isSelected={isSelected}
                                                        onSelect={() => select({ kind: 'finding', key }, isSelected)}
                                                    />
                                                )
                                            })}
                                        </ul>
                                    </div>
                                ))}
                            </div>
                        )}
                        {(listedChecks.length > 0 || exposureChecksMissing) && (
                            <div className="border-t">
                                <HealthCheckList
                                    checks={listedChecks}
                                    exposureChecksMissing={exposureChecksMissing}
                                    selectedKey={selection.kind === 'check' ? selection.key : null}
                                    onSelect={(check) => {
                                        const isSelected = selection.kind === 'check' && selection.key === check.key
                                        if (select({ kind: 'check', key: check.key }, isSelected)) {
                                            reportHealthCheckExpanded(check)
                                        }
                                    }}
                                />
                            </div>
                        )}
                    </div>
                </nav>
                <section
                    ref={detailRef}
                    aria-label="Health check details"
                    className={cn(
                        'flex-1 min-w-0 flex-col gap-4 p-4 @min-[48rem]/health-checks:flex @min-[48rem]/health-checks:p-6 @min-[48rem]/health-checks:sticky @min-[48rem]/health-checks:top-(--scene-layout-header-height) @min-[48rem]/health-checks:self-start',
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
                        <HealthFindingDetail
                            finding={selection.finding}
                            check={checks.find(({ key }) => key === selection.finding.check) ?? null}
                            units={units}
                            exposures={exposures}
                            checkedAt={selection.finding.check ? checkedAt(selection.finding.check) : null}
                            onActedOn={onFindingActedOn}
                        />
                    ) : selection.kind === 'check' ? (
                        <HealthCheckDetail
                            check={selection.check}
                            units={units}
                            exposures={exposures}
                            checkedAt={checkedAt(selection.check.key)}
                        />
                    ) : (
                        <HealthOverviewDetail checks={checks} findings={findings} setup={setup} exposures={exposures} />
                    )}
                </section>
            </div>
        </div>
    )
}
