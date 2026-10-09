/** A titled table of settings rows with the Setting / Project / Mine column header. */
export function SettingsTable({
    title,
    description,
    children,
}: {
    title: string
    description: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="@container overflow-hidden rounded border border-primary bg-surface-primary">
            <header className="flex flex-col gap-0.5 px-4 py-3">
                <h3 className="m-0 text-base font-semibold">{title}</h3>
                <p className="m-0 text-xs text-secondary">{description}</p>
            </header>
            <div className="hidden grid-cols-[minmax(0,1fr)_minmax(0,14rem)_minmax(0,16rem)] gap-3 border-t border-primary px-4 py-1.5 text-xxs font-semibold uppercase tracking-wide text-secondary @min-[48rem]:grid">
                <span>Setting</span>
                <span>Project</span>
                <span>Mine</span>
            </div>
            {children}
        </section>
    )
}
