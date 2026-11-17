export function EmailFieldRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <label className="flex items-center gap-2 min-h-8">
            <span className="w-24 shrink-0 text-xs text-secondary">{label}</span>
            <div className="flex-1 min-w-0 flex items-center gap-1">{children}</div>
        </label>
    )
}
