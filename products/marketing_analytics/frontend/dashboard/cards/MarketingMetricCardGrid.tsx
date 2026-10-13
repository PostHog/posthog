/** Breaks on its own width, because the scene loses ~520px to the nav and an open side panel.
 * auto-fit rather than a fixed column count so a row of cards always spans the full width. */
export function MarketingMetricCardGrid({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="@container">
            <div className="grid gap-2 grid-cols-[repeat(auto-fit,minmax(min(100%,11rem),1fr))]">{children}</div>
        </div>
    )
}
