import type { FrictionGroupShareApi } from '../generated/api.schemas'
import { FRICTION_GROUP_COLORS, FRICTION_GROUP_ORDER } from '../lib/friction'

/** A friction score's groups as colored segments that fill a comparison bar. */
export function FrictionGroupSegments({ groups }: { groups: FrictionGroupShareApi[] }): JSX.Element {
    const total = groups.reduce((sum, share) => sum + share.score, 0)
    return (
        <div className="flex h-full">
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
