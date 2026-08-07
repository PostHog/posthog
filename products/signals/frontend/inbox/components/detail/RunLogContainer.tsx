export function RunLogContainer({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="h-96 w-full overflow-hidden rounded border border-primary bg-surface-primary">{children}</div>
    )
}
