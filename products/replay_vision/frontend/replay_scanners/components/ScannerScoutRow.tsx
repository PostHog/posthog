import { useActions, useValues } from 'kea'

import { IconChevronRight, IconEye, IconGear, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { ProjectTimezoneHint } from 'lib/components/ScheduledRunStatus'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { cn } from 'lib/utils/css-classes'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import { ScoutNextRunLabel } from 'products/signals/frontend/inbox/components/config/scouts/ScoutNextRunLabel'
import { nextRunAt, scoutCadenceLabel } from 'products/signals/frontend/inbox/utils/scoutGroups'
import { scoutDisplayName } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerScoutLogic } from '../scannerScoutLogic'

const CLOCK_TIME_RE = /\d{1,2}:\d{2}/

/** One scout on the scanner's Scouts tab: name, cadence, the on/off switch, its
 * settings, and the link into the Inbox (the one place the underlying scout shows through). */
export function ScannerScoutRow({
    scannerId,
    scannerName,
    config,
}: {
    scannerId: string
    scannerName: string
    config: SignalScoutConfigApi
}): JSX.Element {
    const logic = scannerScoutLogic({ scannerId, scannerName })
    const {
        updatingScoutIds,
        deletingScoutIds,
        manualRunScoutIds,
        expandedSkillNames,
        reportsBySkill,
        scoutReportsLoading,
        scoutReportsFailed,
        rollups,
    } = useValues(logic)
    const {
        openScoutSettings,
        updateScoutConfig,
        deleteScout,
        toggleScoutExpanded,
        openReport,
        runScoutNow,
        loadScoutReports,
    } = useActions(logic)
    const { currentTeam } = useValues(teamLogic)
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    // Deleting a scout or switching it off changes what this scanner watches.
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)
    const updating = updatingScoutIds.includes(config.id)
    const expanded = expandedSkillNames.includes(config.skill_name)
    const reports = reportsBySkill.get(config.skill_name) ?? []
    // The request returns as soon as the workflow is dispatched, so the button's own loading state
    // clears in a second while the run takes minutes. Without this the button looks ready again and
    // the next click is refused by the backend's in-flight check with a bare 409.
    const runDisabledReason =
        editDisabledReason ?? (rollups.get(config.skill_name)?.runningRun ? 'This scout is already running' : undefined)

    const cadenceText = capitalizeFirstLetter(scoutCadenceLabel(config))
    // Only a clock time is evaluated in the project timezone; "every 30 minutes" has none to name.
    const namesClockTime = CLOCK_TIME_RE.test(cadenceText)
    const hasNextRun = nextRunAt(config, currentTeam?.timezone ?? 'UTC', new Date()) !== null

    return (
        <div className={cn('flex flex-col rounded border bg-surface-primary', !config.enabled && 'opacity-65')}>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
                {/* Outside the expand button: the next-run popover has clickable rows. */}
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <button
                        type="button"
                        className="-mx-1 flex min-w-0 cursor-pointer items-center gap-2 rounded px-1 py-1 text-left transition-colors hover:bg-surface-secondary"
                        onClick={() => toggleScoutExpanded(config.skill_name)}
                        aria-label={`${expanded ? 'Hide' : 'Show'} reports from ${scoutDisplayName(config)}`}
                        aria-expanded={expanded}
                        data-attr="vision-scout-row-expand"
                    >
                        <IconChevronRight
                            className={cn('shrink-0 text-base transition-transform', expanded && 'rotate-90')}
                        />
                        <span className="truncate text-sm font-medium">{scoutDisplayName(config)}</span>
                    </button>
                    <span className="pl-6 text-[11px] text-muted">
                        {cadenceText}
                        {namesClockTime && (
                            <>
                                {' '}
                                <ProjectTimezoneHint />
                            </>
                        )}
                        {hasNextRun && (
                            <>
                                {' · next run '}
                                <ScoutNextRunLabel config={config} />
                            </>
                        )}
                    </span>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    <Tooltip title="Scout settings">
                        <LemonButton
                            size="small"
                            icon={<IconGear />}
                            onClick={() => openScoutSettings(config.skill_name)}
                            aria-label={`${scoutDisplayName(config)} settings`}
                            data-attr="vision-scout-row-settings"
                        />
                    </Tooltip>
                    <Tooltip title="Delete this scout">
                        <LemonButton
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            loading={deletingScoutIds.includes(config.id)}
                            disabledReason={editDisabledReason}
                            onClick={() =>
                                LemonDialog.open({
                                    title: `Delete ${scoutDisplayName(config).toLowerCase()}?`,
                                    description:
                                        'This stops its scheduled runs permanently and cannot be undone. Reports it already filed stay in your inbox.',
                                    primaryButton: {
                                        children: 'Delete',
                                        status: 'danger',
                                        onClick: () => deleteScout(config.id, 'replay_vision_scanner'),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                            aria-label={`Delete ${scoutDisplayName(config)}`}
                            data-attr="vision-scout-row-delete"
                        />
                    </Tooltip>
                    <Tooltip title={config.enabled ? 'Pause this scout' : 'Resume this scout'}>
                        <span>
                            {/* Not the shared ScoutEnabledSwitch: it has no way to carry the scanner's
                            edit gate, and a viewer must not be able to switch a scout off. */}
                            <LemonSwitch
                                size="small"
                                checked={config.enabled}
                                onChange={(checked) => updateScoutConfig(config.id, { enabled: checked })}
                                loading={updating}
                                disabledReason={editDisabledReason ?? (updating ? 'Saving scout settings' : undefined)}
                                aria-label={`${scoutDisplayName(config)} enabled`}
                            />
                        </span>
                    </Tooltip>
                </div>
            </div>
            {expanded && scoutReportsLoading && reports.length === 0 && (
                <div className="border-t border-primary px-4 py-2 pl-12">
                    <LemonSkeleton className="h-8 w-full" />
                </div>
            )}
            {expanded && !scoutReportsLoading && scoutReportsFailed && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-primary px-4 py-2 pl-12">
                    <span className="text-sm text-muted">Couldn't load this scout's reports.</span>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => loadScoutReports()}
                        data-attr="vision-scout-row-reports-retry"
                    >
                        Try again
                    </LemonButton>
                </div>
            )}
            {/* "No reports filed yet" is a verdict about reports that arrived, and Run now spends
                credits, so neither belongs on a roster whose reports failed to load or have not
                loaded: both leave the list empty, and neither means the scout filed nothing. */}
            {expanded && !scoutReportsLoading && !scoutReportsFailed && reports.length === 0 && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-primary px-4 py-2 pl-12">
                    <span className="text-sm text-muted">
                        No reports filed yet. The first arrives after the next scheduled run.
                    </span>
                    <LemonButton
                        size="small"
                        type="secondary"
                        loading={manualRunScoutIds.includes(config.id)}
                        disabledReason={runDisabledReason}
                        onClick={() => runScoutNow(config.id)}
                        data-attr="vision-scout-row-run-now"
                    >
                        Run now
                    </LemonButton>
                </div>
            )}
            {expanded && !scoutReportsLoading && !scoutReportsFailed && reports.length > 0 && (
                <div className="border-t border-primary px-4 py-2 pl-12">
                    {/* Same shape as the scanner's observation history, so the two lists read alike. */}
                    <LemonTable
                        embedded
                        showHeader={false}
                        size="small"
                        rowKey="report_id"
                        dataSource={reports}
                        columns={[
                            {
                                title: '',
                                key: 'id',
                                render: (_, report) => <span className="font-mono text-xs">{report.report_id}</span>,
                            },
                            {
                                title: '',
                                key: 'touchedAt',
                                // Baseline, not centre: `TZLabel` carries a dotted bottom border, so
                                // centring the two boxes puts its text half a pixel off, and which way
                                // that rounds shifts with the width of the digits.
                                render: (_, report) => (
                                    <span className="inline-flex items-baseline gap-1 text-muted">
                                        Filed <TZLabel time={report.filed_at} />
                                    </span>
                                ),
                            },
                            {
                                title: '',
                                key: 'actions',
                                width: 1,
                                render: (_, report) => (
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        icon={<IconEye />}
                                        onClick={() => openReport(report.report_id)}
                                        className="whitespace-nowrap"
                                        data-attr="vision-scout-row-report"
                                    >
                                        View report
                                    </LemonButton>
                                ),
                            },
                        ]}
                    />
                </div>
            )}
        </div>
    )
}
