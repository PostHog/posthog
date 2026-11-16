export function QuillSeriesSwatch({ color }: { color: string }): JSX.Element {
    return (
        <span
            className="inline-block size-3.5 shrink-0 rounded-full border-2"
            // The series color comes from the chart's palette or the user's choice, so it can't be a token.
            // eslint-disable-next-line react/forbid-dom-props
            style={{ borderColor: color, backgroundColor: `color-mix(in srgb, ${color} 20%, transparent)` }}
        />
    )
}
