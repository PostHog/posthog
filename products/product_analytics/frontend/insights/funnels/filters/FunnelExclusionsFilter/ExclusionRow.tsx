export function ExclusionRow({
    seriesIndicator,
    filter,
    suffix,
}: {
    seriesIndicator?: JSX.Element | string
    suffix?: JSX.Element | string
    filter?: JSX.Element | string
}): JSX.Element {
    return (
        <div className="w-full">
            <div className="flex flex-nowrap items-center">
                <div className="px-2">{seriesIndicator}</div>
                <div className="flex-1">{filter}</div>
            </div>
            <div className="ml-9">{suffix}</div>
        </div>
    )
}
