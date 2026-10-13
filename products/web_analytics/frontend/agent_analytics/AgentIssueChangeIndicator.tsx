import clsx from 'clsx'

import { IconTrending } from '@posthog/icons'
import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { percentage } from 'lib/utils/numbers'

export type ChangeSentiment = 'higher-is-better' | 'lower-is-better' | 'neutral'

export const AgentIssueChangeIndicator = ({
    changePct,
    sentiment = 'lower-is-better',
}: {
    changePct: number | null
    sentiment?: ChangeSentiment
}): JSX.Element | null => {
    if (changePct === null) {
        return null
    }

    const increased = changePct > 0
    const decreased = changePct < 0
    const Icon = increased ? IconTrending : decreased ? IconTrendingDown : IconTrendingFlat
    const favorable = sentiment === 'neutral' ? null : sentiment === 'higher-is-better' ? increased : decreased
    const tagType: LemonTagType = favorable === null ? 'muted' : favorable ? 'success' : 'danger'
    const direction = increased ? 'more' : decreased ? 'fewer' : 'the same as'

    return (
        <Tooltip
            title={
                changePct === 0
                    ? 'No change from the previous period'
                    : `${percentage(Math.abs(changePct) / 100, 0)} ${direction} than the previous period`
            }
        >
            <LemonTag
                type={tagType}
                size="small"
                icon={<Icon />}
                className={clsx('tabular-nums', sentiment === 'neutral' && 'text-secondary')}
            >
                {changePct > 0 ? '+' : ''}
                {percentage(changePct / 100, 0)}
            </LemonTag>
        </Tooltip>
    )
}
