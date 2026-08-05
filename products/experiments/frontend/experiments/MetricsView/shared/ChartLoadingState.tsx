import { Spinner } from 'lib/lemon-ui/Spinner'

interface ChartLoadingStateProps {
    height: number
}

export function ChartLoadingState({ height }: ChartLoadingStateProps): JSX.Element {
    return (
        <div
            className="flex items-center justify-center gap-2 text-[14px] font-normal"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: `${height}px` }}
        >
            <Spinner className="text-lg" />
            <span>Loading results&hellip;</span>
        </div>
    )
}
