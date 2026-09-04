import { IconPencil } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { ScoutGroupKey, scoutSubtitle } from '../../../utils/scoutGroups'
import { prettifyScoutSkillName, ScoutRollup } from '../../../utils/scoutRunsWindow'
import { scoutWriteScopeLabels } from './scoutWriteScopes'

const SUBTITLE_TONE_CLASS = {
    danger: 'text-danger',
    warning: 'text-warning',
    muted: 'text-muted',
} as const

export function ScoutNameCell({
    config,
    group,
    rollup,
}: {
    config: SignalScoutConfig
    group: ScoutGroupKey
    rollup: ScoutRollup | undefined
}): JSX.Element {
    const subtitle = scoutSubtitle(config, rollup, new Date())
    // Only for a scout that holds write access. Every other scout reads the project, so a chip on
    // those would label the norm and hide the exception in the noise.
    const writeLabels = scoutWriteScopeLabels(config.write_scopes)
    return (
        <div className="flex flex-col gap-0.5 py-0.5">
            <div className="flex items-center gap-2">
                <Link to={urls.inboxScout(config.skill_name)} subtle className="truncate text-sm font-medium">
                    {prettifyScoutSkillName(config.skill_name)}
                </Link>
                {writeLabels.length > 0 && (
                    <Tooltip title={`This scout can write ${writeLabels.join(', ').toLowerCase()} in this project`}>
                        <LemonTag size="small" type="option" icon={<IconPencil />}>
                            {writeLabels.join(', ')}
                        </LemonTag>
                    </Tooltip>
                )}
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
