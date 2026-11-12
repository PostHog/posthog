export function HeadlineNumber({ value, label }: { value: number; label: string }): JSX.Element {
    return (
        <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-semibold">{value}</span>
            <span className="text-secondary">{label}</span>
        </div>
    )
}
