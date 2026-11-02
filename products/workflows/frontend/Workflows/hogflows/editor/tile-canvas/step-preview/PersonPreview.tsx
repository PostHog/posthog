export function PersonPreview({ properties }: { properties: [key: string, value: string][] }): JSX.Element | null {
    if (!properties.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-1 rounded-md border p-2.5 text-left font-mono text-[12px]">
            {properties.map(([key, value]) => (
                <div key={key}>
                    <span className="text-secondary">{key}</span> to <span className="font-semibold">{value}</span>
                </div>
            ))}
        </div>
    )
}
