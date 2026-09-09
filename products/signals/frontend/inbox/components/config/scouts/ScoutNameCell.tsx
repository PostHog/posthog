import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { ScoutGroupKey, scoutSubtitle } from '../../../utils/scoutGroups'
import { prettifyScoutSkillName, ScoutRollup } from '../../../utils/scoutRunsWindow'
import { ScoutWriteAccessTag } from './ScoutWriteAccessTag'

const SUBTITLE_TONE_CLASS = {
    danger: 'text-danger',
    warning: 'text-warning',
    muted: 'text-muted',
} as const

export function ScoutNameCell({
    config,
    group,
    rollup,
    compact = false,
}: {
    config: SignalScoutConfig
    group: ScoutGroupKey
    rollup: ScoutRollup | undefined
    /** The table's compact layout, where the name column is too narrow for the tag's labels. */
    compact?: boolean
}): JSX.Element {
    const subtitle = scoutSubtitle(config, rollup, new Date())
    return (
        <div className="flex flex-col gap-0.5 py-0.5">
            <div className="flex items-center gap-2">
                <Link to={urls.inboxScout(config.skill_name)} subtle className="truncate text-sm font-medium">
                    {prettifyScoutSkillName(config.skill_name)}
                </Link>
                <ScoutWriteAccessTag writeScopes={config.write_scopes} emit={config.emit} compact={compact} />
                {config.auto_pause_exempt && group === 'watching' && (
                    <Tooltip title="Exempt from auto-pause — this scout is supposed to stay quiet">
                        <LemonTag size="small">Quiet by design</LemonTag>
                    </Tooltip>
                )}
            </div>
            {subtitle && (
                <span className={cn('line-clamp-1 text-[11.5px]', SUBTITLE_TONE_CLASS[subtitle.tone])}>
                    {subtitle.text}
                </span>
            )}
        </div>
    )
}
