/** A centered note in a metric widget's chart area, for empty and ineligible states. */
export function MetricsWidgetMessage({ children }: { children: string }): JSX.Element {
    return (
        <div className="flex-1 flex items-center justify-center p-4 text-center text-secondary text-sm">{children}</div>
    )
}
