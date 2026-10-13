const KINDS: [string, string][] = [
    ['test', 'Test'],
    ['check', 'Check'],
    ['build', 'Build'],
    ['setup', 'Setup or report'],
    ['matrix', 'Matrix'],
]

/** What each node outline means. Shown while job nodes are on screen. */
export function CIExplorerLegend(): JSX.Element {
    return (
        <div className="CIExplorer__legend">
            {KINDS.map(([kind, label]) => (
                <span key={kind}>
                    <i className={`CIExplorer__swatch CIExplorer__swatch--${kind}`} />
                    {label}
                </span>
            ))}
        </div>
    )
}
