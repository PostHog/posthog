export function SendDayPickerLegend(): JSX.Element {
    return (
        <div
            className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-secondary"
            data-attr="send-day-picker-legend"
        >
            <span className="flex items-center gap-1">
                <span className="size-3 shrink-0 rounded-sm border bg-warning-highlight" />
                Too close to other sends
            </span>
            <span className="flex items-center gap-1">
                <span className="size-3 shrink-0 rounded-sm border-2 border-dashed border-success" />
                Suggested
            </span>
        </div>
    )
}
