/** Breaks on its own width, because the scene loses ~520px to the nav and an open side panel. */
export function MarketingMetricCardGrid({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="@container">
            <div className="grid gap-2 grid-cols-2 @xl:grid-cols-3 @5xl:grid-cols-5">{children}</div>
        </div>
    )
}
