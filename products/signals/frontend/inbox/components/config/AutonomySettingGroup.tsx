import { ReactNode } from 'react'

/**
 * A run of Autonomy rows that share one scope, such as the project or the current user. The scope
 * is stated once in the heading, so each row does not have to repeat who it applies to.
 */
export function AutonomySettingGroup({
    title,
    description,
    children,
}: {
    title: string
    description?: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1 py-4 first:pt-2 last:pb-0">
            <div className="flex flex-col gap-0.5">
                <h4 className="m-0 text-xs font-semibold uppercase tracking-wide text-tertiary">{title}</h4>
                {description && <p className="m-0 text-xs leading-snug text-secondary">{description}</p>}
            </div>
            <div className="flex flex-col divide-y divide-primary [&>*:last-child]:pb-0">{children}</div>
        </div>
    )
}
