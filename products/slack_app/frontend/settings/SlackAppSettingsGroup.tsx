export function SlackAppSettingsGroup({
    title,
    description,
    children,
}: {
    title?: string
    description?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            {title ? (
                <div>
                    <h3 className="text-sm font-semibold m-0">{title}</h3>
                    {description ? <p className="text-secondary text-xs m-0">{description}</p> : null}
                </div>
            ) : null}
            <div className="rounded border bg-surface-primary divide-y">{children}</div>
        </section>
    )
}
