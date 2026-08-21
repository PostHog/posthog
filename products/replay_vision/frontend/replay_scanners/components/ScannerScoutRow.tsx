import { useActions, useValues } from 'kea'

import { IconChevronRight, IconEye, IconGear, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'
import { nextRunAt, scoutCadenceLabel } from 'products/signals/frontend/inbox/utils/scoutGroups'
import { prettifyScoutSkillName } from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerScoutLogic } from '../scannerScoutLogic'

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
    const { updatingScoutIds, deletingScoutIds, expandedSkillNames, reportsBySkill } = useValues(logic)
    const { openScoutSettings, updateScoutConfig, deleteScout, toggleScoutExpanded, openReport } = useActions(logic)
    const { currentTeam } = useValues(teamLogic)
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    // Deleting a scout or switching it off changes what this scanner watches.
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)
    const updating = updatingScoutIds.includes(config.id)
    const expanded = expandedSkillNames.includes(config.skill_name)
    const reports = reportsBySkill.get(config.skill_name) ?? []

    const timezone = currentTeam?.timezone ?? 'UTC'
    const now = new Date()
    const next = nextRunAt(config, timezone, now)
    const nextRunText =
        !next || !config.enabled
            ? null
            : next <= now
              ? 'due now'
              : next.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', timeZone: timezone })

    return (
        <div className={cn('flex flex-col rounded border bg-surface-primary', !config.enabled && 'opacity-65')}>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
                <LemonButton
                    size="small"
                    icon={<IconChevronRight className={cn('transition-transform', expanded && 'rotate-90')} />}
                    onClick={() => toggleScoutExpanded(config.skill_name)}
                    aria-label={`${expanded ? 'Hide' : 'Show'} reports from ${prettifyScoutSkillName(config.skill_name)}`}
                    aria-expanded={expanded}
                    data-attr="vision-scout-row-expand"
                />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-sm font-medium">{prettifyScoutSkillName(config.skill_name)}</span>
                    <span className="text-[11px] text-muted">
                        {scoutCadenceLabel(config)}
                        {nextRunText && ` · next run ${nextRunText}`}
                    </span>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    <Tooltip title="Scout settings">
                        <LemonButton
                            size="small"
                            icon={<IconGear />}
                            onClick={() => openScoutSettings(config.skill_name)}
                            aria-label={`${prettifyScoutSkillName(config.skill_name)} settings`}
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
                                    title: `Delete ${prettifyScoutSkillName(config.skill_name).toLowerCase()}?`,
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
                            aria-label={`Delete ${prettifyScoutSkillName(config.skill_name)}`}
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
                                aria-label={`${prettifyScoutSkillName(config.skill_name)} enabled`}
                            />
                        </span>
                    </Tooltip>
                </div>
            </div>
            {expanded && (
                <div className="border-t border-primary px-4 py-2 pl-12">
                    {/* Same shape as the scanner's observation history, so the two lists read alike. */}
                    <LemonTable
                        embedded
                        showHeader={false}
                        size="small"
                        rowKey="report_id"
                        dataSource={reports}
                        emptyState="No reports filed yet."
                        columns={[
                            {
                                title: '',
                                key: 'id',
                                render: (_, report) => <span className="font-mono text-xs">{report.report_id}</span>,
                            },
                            {
                                title: '',
                                key: 'touchedAt',
                                render: (_, report) => (
                                    <span className="text-muted">
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
