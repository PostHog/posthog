export function WizardRunDiffStats({
    additions,
    removals,
}: {
    additions: number | null
    removals: number | null
}): JSX.Element | null {
    if (additions === null || removals === null) {
        return null
    }

    return (
        <span className="flex items-center gap-1.5 text-xs font-medium" data-attr="wizard-run-diff-stats">
            <span className="text-success">+{additions.toLocaleString()}</span>
            <span className="text-danger">-{removals.toLocaleString()}</span>
        </span>
    )
}
