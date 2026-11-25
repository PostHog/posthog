/** `group` is for a row of buttons. Inside a label, a click on the row's name would press the first one. */
export function EmailFieldRow({
    label,
    group = false,
    children,
}: {
    label: string
    group?: boolean
    children: React.ReactNode
}): JSX.Element {
    const Row = group ? 'div' : 'label'
    return (
        <Row className="flex items-center gap-2 min-h-8" {...(group ? { role: 'group', 'aria-label': label } : {})}>
            <span className="w-24 shrink-0 text-xs text-secondary">{label}</span>
            <div className="flex-1 min-w-0 flex items-center gap-1">{children}</div>
        </Row>
    )
}
