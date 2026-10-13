/** A bordered list with one row per setting. */
export function SettingsList({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="divide-y divide-primary overflow-hidden rounded border border-primary bg-surface-primary">
            {children}
        </div>
    )
}
