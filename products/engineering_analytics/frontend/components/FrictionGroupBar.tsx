import { Tooltip } from '@posthog/lemon-ui'

import type { FrictionGroupShareApi } from '../generated/api.schemas'
import { timesTypical } from '../lib/format'
import { FRICTION_GROUP_COLORS, FRICTION_GROUP_LABELS, FRICTION_GROUP_ORDER } from '../lib/friction'

/** A friction score split by group, as one stacked bar. Its length is the score against ``max``. */
export function FrictionGroupBar({ groups, max }: { groups: FrictionGroupShareApi[]; max: number }): JSX.Element {
    const byGroup = new Map(groups.map((share) => [share.group, share.score]))
    const total = groups.reduce((sum, share) => sum + share.score, 0)
    const tooltip = (
        <div className="flex flex-col gap-0.5">
            {FRICTION_GROUP_ORDER.map((group) => (
                <div key={group} className="flex items-center gap-2">
                    <span className={`size-2 rounded-sm ${FRICTION_GROUP_COLORS[group]}`} />
                    <span className="flex-1">{FRICTION_GROUP_LABELS[group]}</span>
                    <span className="tabular-nums">{timesTypical(byGroup.get(group) ?? 0)}</span>
                </div>
            ))}
        </div>
    )
    return (
        <Tooltip title={tooltip}>
            <div
                className="h-2 w-full rounded-sm bg-fill-secondary"
                tabIndex={0}
                aria-label={FRICTION_GROUP_ORDER.map(
                    (group) => `${FRICTION_GROUP_LABELS[group]} ${timesTypical(byGroup.get(group) ?? 0)}`
                ).join(', ')}
            >
                <div
                    className="flex h-full overflow-hidden rounded-sm"
                    style={{ width: `${max > 0 ? (total / max) * 100 : 0}%` }}
                >
                    {FRICTION_GROUP_ORDER.map((group) => {
                        const score = byGroup.get(group) ?? 0
                        return score > 0 ? (
                            <div
                                key={group}
                                className={FRICTION_GROUP_COLORS[group]}
                                style={{ width: `${(score / total) * 100}%` }}
                            />
                        ) : null
                    })}
                </div>
            </div>
        </Tooltip>
    )
}
