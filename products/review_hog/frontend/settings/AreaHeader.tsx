/** The large heading that opens one area of the Settings tab, with the area's intro under it. */
export function AreaHeader({
    title,
    subtitle,
    children,
}: {
    title: string
    subtitle: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <header className="flex max-w-220 flex-col gap-1.5">
            <h2 className="m-0 text-xl font-bold">
                {title} <span className="font-normal text-secondary">· {subtitle}</span>
            </h2>
            {children}
        </header>
    )
}
