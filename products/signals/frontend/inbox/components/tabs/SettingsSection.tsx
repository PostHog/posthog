import { ReactNode } from 'react'

/** One titled block of the Settings tab: heading + one-line context over the section's controls. */
export function SettingsSection({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-3">
            <div className="flex flex-col gap-0.5">
                <h3 className="m-0 text-sm font-semibold text-default">{title}</h3>
                {description && <p className="m-0 max-w-2xl text-xs leading-snug text-secondary">{description}</p>}
            </div>
            {children}
        </section>
    )
}
