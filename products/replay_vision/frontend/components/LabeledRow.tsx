/** A label-above-content row used across the readonly config and observation detail cards. */
export function LabeledRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div>
            <div className="text-xs text-muted mb-0.5">{label}</div>
            <div className="text-sm">{children}</div>
        </div>
    )
}
