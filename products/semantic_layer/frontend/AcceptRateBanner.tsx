import { ACCEPTANCE_STATS } from './proposalsMockData'

export function AcceptRateBanner(): JSX.Element {
    const { approved30d, rejected30d, edited30d, acceptRate } = ACCEPTANCE_STATS
    return (
        <div className="flex items-center gap-4 px-4 py-2 border rounded bg-surface-primary text-sm">
            <span className="font-medium">Last 30 days</span>
            <div className="flex items-center gap-3 text-muted-alt">
                <span>
                    <span className="font-semibold text-success">{approved30d}</span> approved
                </span>
                <span aria-hidden>·</span>
                <span>
                    <span className="font-semibold text-danger">{rejected30d}</span> rejected
                </span>
                <span aria-hidden>·</span>
                <span>
                    <span className="font-semibold">{edited30d}</span> edited
                </span>
                <span aria-hidden>·</span>
                <span>
                    <span className="font-semibold">{Math.round(acceptRate * 100)}%</span> accept rate
                </span>
            </div>
            <div className="ml-auto text-xs text-muted-alt">
                The agent learns from rejections — reasons feed back into future proposals.
            </div>
        </div>
    )
}
