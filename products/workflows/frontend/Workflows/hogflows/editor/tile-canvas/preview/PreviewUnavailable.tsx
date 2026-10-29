export function PreviewUnavailable(): JSX.Element {
    return (
        <div className="rounded-md border px-3 py-2 text-xs text-muted-foreground">
            The steps could not be drawn here. Open the workflow in PostHog to see them.
        </div>
    )
}
