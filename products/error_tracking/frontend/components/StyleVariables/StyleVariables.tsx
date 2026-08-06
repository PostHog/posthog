export function StyleVariables({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element {
    return <div className={className}>{children}</div>
}
