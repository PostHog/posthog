// A fixed label column keeps stacked lists on the page aligned with each other.
export function FactList({ children }: { children: React.ReactNode }): JSX.Element {
    return <dl className="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm m-0">{children}</dl>
}

export function Fact({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <>
            <dt className="text-muted truncate" title={label}>
                {label}
            </dt>
            <dd className="m-0 min-w-0">{children}</dd>
        </>
    )
}
