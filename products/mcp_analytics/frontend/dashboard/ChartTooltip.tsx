export function ChartTooltip({ title, rows }: { title: string; rows: [string, string][] }): JSX.Element {
    return (
        <div className="rounded-md border border-primary bg-surface-primary px-2.5 py-2 text-xs shadow-md">
            <div className="mb-1 font-medium text-primary">{title}</div>
            {rows.map(([label, value]) => (
                <div key={label} className="flex justify-between gap-4 text-secondary">
                    <span>{label}</span>
                    <span className="font-mono text-primary">{value}</span>
                </div>
            ))}
        </div>
    )
}
