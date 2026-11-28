export function SlackAppSettingRow({
    label,
    description,
    children,
}: {
    label: string
    description: string
    children: JSX.Element
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
            <div className="flex-1 min-w-60">
                <div className="font-semibold">{label}</div>
                <div className="text-secondary text-sm">{description}</div>
            </div>
            <div className="flex justify-end">{children}</div>
        </div>
    )
}
