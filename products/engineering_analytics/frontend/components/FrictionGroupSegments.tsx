import type { FrictionGroupShareApi } from '../generated/api.schemas'
import { timesTypical } from '../lib/format'
import { FRICTION_GROUP_COLORS, FRICTION_GROUP_LABELS, FRICTION_GROUP_ORDER } from '../lib/friction'

/** A friction score's groups as colored segments that fill a comparison bar. */
export function FrictionGroupSegments({ groups }: { groups: FrictionGroupShareApi[] }): JSX.Element {
    const total = groups.reduce((sum, share) => sum + share.score, 0)
    const label = FRICTION_GROUP_ORDER.map(
        (group) =>
            `${FRICTION_GROUP_LABELS[group]} ${timesTypical(groups.find((share) => share.group === group)?.score ?? 0)}`
    ).join(', ')
    return (
        <div className="flex h-full" role="img" aria-label={label}>
            {FRICTION_GROUP_ORDER.map((group) => {
                const score = groups.find((share) => share.group === group)?.score ?? 0
                return score > 0 && total > 0 ? (
                    <div
                        key={group}
                        className={FRICTION_GROUP_COLORS[group]}
                        style={{ width: `${(score / total) * 100}%` }}
                    />
                ) : null
            })}
        </div>
    )
}
