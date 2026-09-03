import { useValues } from 'kea'

import { IconArrowUpRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'

import { nextRunAt, scoutCadenceLabel } from '../../../utils/scoutGroups'
import { prettifyScoutSkillName } from '../../../utils/scoutRunsWindow'
import { ScoutLifecycleBadge } from './ScoutBadges'
import { ScoutEnabledSwitch } from './ScoutConfigControls'

/**
 * A compact scout row for surfaces outside the roster — product pages that show the handful of
 * scouts they own (e.g. AI observability). Deliberately read-mostly: name, cadence, the enable
 * switch, and a link into the scout's own page, which is where the rest of it lives.
 */
export function ScoutSummaryRow({
    config,
    onUpdate,
    updating = false,
}: {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const timezone = currentTeam?.timezone ?? 'UTC'
    const now = new Date()
    const next = nextRunAt(config, timezone, now)
    // Shown in the project timezone, the one the cadence is stated in; a rolling scout past its
    // interval is waiting on the scheduler rather than scheduled for a time that has passed.
    const nextRunText =
        !next || !config.enabled ? null : next <= now ? 'due now' : dayjs(next).tz(timezone).format('h:mm A')

    return (
        <div
            className={cn(
                'flex flex-wrap items-center gap-x-4 gap-y-2 rounded border border-primary bg-surface-primary px-4 py-2.5',
                !config.enabled && 'opacity-65'
            )}
        >
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex items-center gap-2">
                    <Tooltip title={config.description || undefined}>
                        <Link
                            to={urls.inboxScout(config.skill_name)}
                            subtle
                            className="truncate text-sm font-medium min-w-[6rem]"
                        >
                            {prettifyScoutSkillName(config.skill_name)}
                        </Link>
                    </Tooltip>
                    {!config.emit && (
                        <LemonTag size="small" type="option">
                            Dry run
                        </LemonTag>
                    )}
                    <ScoutLifecycleBadge config={config} />
                </div>
                <span className="text-[11px] text-muted">
                    {scoutCadenceLabel(config)}
                    {nextRunText && ` · next run ${nextRunText}`}
                </span>
            </div>
            <div className="flex shrink-0 items-center gap-2">
                <ScoutEnabledSwitch config={config} onUpdate={onUpdate} updating={updating} />
                <Tooltip title="Open this scout">
                    <LemonButton
                        size="small"
                        icon={<IconArrowUpRight />}
                        to={urls.inboxScout(config.skill_name)}
                        aria-label={`Open the ${config.skill_name} scout`}
                    />
                </Tooltip>
            </div>
        </div>
    )
}
