import { FRICTION_GROUP_COLORS, FRICTION_GROUP_LABELS, FRICTION_GROUP_ORDER } from '../lib/friction'

export function FrictionGroupLegend(): JSX.Element {
    return (
        <span className="flex flex-wrap items-center gap-3">
            {FRICTION_GROUP_ORDER.map((group) => (
                <span key={group} className="flex items-center gap-1">
                    <span className={`size-2 rounded-sm ${FRICTION_GROUP_COLORS[group]}`} />
                    {FRICTION_GROUP_LABELS[group]}
                </span>
            ))}
        </span>
    )
}
