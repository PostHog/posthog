export function HealthChecksCoverageNote({ isDraft }: { isDraft: boolean }): JSX.Element {
    return (
        // Spans only, because the note sits inside the button that opens the overview.
        // pinned: `data-attr` value, so renaming it breaks autocapture insights
        <span className="text-secondary" data-attr="experiment-health-summary">
            {isDraft && <span>More checks run after launch. </span>}
            <span>We're still adding checks, so they don't cover every problem yet.</span>
        </span>
    )
}
