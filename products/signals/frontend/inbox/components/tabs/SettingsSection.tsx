import { ReactNode } from 'react'

/**
 * One block of the Settings tab: heading, one-line context, and the section's controls, together on
 * a bordered card. The card is the only frame on the page — controls inside it separate with rules
 * rather than nesting further boxes.
 */
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
        <section className="flex flex-col gap-3 rounded border border-primary bg-surface-primary p-4">
            <div className="flex flex-col gap-0.5">
                <h3 className="m-0 text-sm font-semibold text-default">{title}</h3>
                {description && <p className="m-0 max-w-2xl text-xs leading-snug text-secondary">{description}</p>}
            </div>
            {children}
        </section>
    )
}
