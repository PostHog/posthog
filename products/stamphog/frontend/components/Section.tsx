export function Section({
    title,
    note,
    children,
}: {
    title?: string
    note?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="min-w-0">
            {title && <h5 className="text-muted mb-1.5">{title}</h5>}
            {/* An auto label column sits against its longest label — a fixed width would open a ragged
                gap beside the short ones. Baseline alignment keeps plain values level with the tag rows. */}
            <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-4 gap-y-1.5 text-xs">{children}</dl>
            {note && <p className="text-muted text-xs mt-2 mb-0">{note}</p>}
        </section>
    )
}
