export function SectionHeader({
    icon,
    title,
    pill,
    action,
    children,
}: {
    icon: JSX.Element
    title: string
    pill?: JSX.Element
    action?: JSX.Element
    children: string
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-primary bg-surface-primary text-secondary *:size-4">
                    {icon}
                </span>
                <h3 className="m-0 text-base font-semibold">{title}</h3>
                {pill}
                {action && <div className="ml-auto">{action}</div>}
            </div>
            {/* Indented so the copy aligns under the title, not the icon tile */}
            <p className="m-0 ml-9 max-w-160 text-xs text-secondary">{children}</p>
        </div>
    )
}
