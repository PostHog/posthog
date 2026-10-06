/** The footer link that opens the quarantined stories this run rendered clean. */
export function CleanQuarantinedToggle({
    cleanCount,
    loadFailed,
    isExpanded,
    onClick,
}: {
    cleanCount: number
    loadFailed: boolean
    isExpanded: boolean
    onClick: () => void
}): JSX.Element {
    if (loadFailed) {
        return <span>Couldn't load the quarantined stories. Reload the page.</span>
    }
    return (
        <button
            type="button"
            onClick={onClick}
            aria-expanded={isExpanded}
            data-attr="visual-review-toggle-clean-quarantined"
            className="shrink-0 text-xs text-muted hover:text-default hover:underline underline-offset-2 transition-colors"
        >
            {isExpanded
                ? 'Hide clean quarantined stories'
                : `${cleanCount} quarantined ${cleanCount === 1 ? 'story' : 'stories'} rendered clean`}
        </button>
    )
}
