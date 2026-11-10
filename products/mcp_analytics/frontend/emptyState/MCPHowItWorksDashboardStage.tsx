import './MCPHowItWorksDashboardStage.scss'

import { IconBrain, IconWarning, IconWrench } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

export function MCPHowItWorksDashboardStage(): JSX.Element {
    return (
        <div className="MCPHowItWorks__dash">
            <div className="MCPHowItWorks__tile MCPHowItWorks__rv [--d:0.1s]">
                <span className="MCPHowItWorks__tile-label">
                    <IconWrench />
                    Tool calls
                </span>
                <span className="MCPHowItWorks__big">12.4k</span>
                <svg className="MCPHowItWorks__spark" viewBox="0 0 100 28" preserveAspectRatio="none">
                    <path
                        className="MCPHowItWorks__draw"
                        pathLength={1}
                        stroke="var(--mcp-how-blue)"
                        d="M0 22 L11 20 L22 23 L33 15 L44 17 L55 10 L66 13 L77 6 L88 8 L100 3"
                    />
                </svg>
            </div>
            <div className="MCPHowItWorks__tile MCPHowItWorks__rv [--d:0.25s]">
                <span className="MCPHowItWorks__tile-label">
                    <IconBrain />
                    Models
                </span>
                <svg className="MCPHowItWorks__spark" viewBox="0 0 120 56" preserveAspectRatio="none">
                    {[14, 30, 46].map((y) => (
                        <line key={y} className="MCPHowItWorks__grid-line" x1="0" y1={y} x2="120" y2={y} />
                    ))}
                    <path
                        className="MCPHowItWorks__area"
                        fill="var(--mcp-how-purple)"
                        fillOpacity=".2"
                        d="M0 44 C12 40 20 46 32 36 S52 30 62 24 S82 26 92 14 S110 10 120 6 L120 56 L0 56 Z"
                    />
                    <path
                        className="MCPHowItWorks__draw"
                        pathLength={1}
                        stroke="var(--mcp-how-purple)"
                        d="M0 44 C12 40 20 46 32 36 S52 30 62 24 S82 26 92 14 S110 10 120 6"
                    />
                    <path
                        className="MCPHowItWorks__draw"
                        pathLength={1}
                        stroke="var(--mcp-how-blue)"
                        d="M0 51 C14 48 24 50 36 45 S58 43 70 38 S96 37 106 31 S116 30 120 28"
                    />
                </svg>
            </div>
            <div className="MCPHowItWorks__tile MCPHowItWorks__struggle MCPHowItWorks__rv [--d:0.4s]">
                <span className="MCPHowItWorks__tile-label">
                    <IconWarning />
                    Error rate
                </span>
                <ErrorRow tool="search_jobs" barClassName="[--w:7%] [--d:0.9s]" rate="4%" />
                <ErrorRow tool="get_listing" barClassName="[--w:16%] [--d:1s]" rate="9%" />
                <ErrorRow tool="book_slot" barClassName="[--w:68%] [--d:1.1s]" rate="38%" bad />
            </div>
        </div>
    )
}

function ErrorRow({
    tool,
    barClassName,
    rate,
    bad = false,
}: {
    tool: string
    /** Sets the bar's `--w` width and `--d` reveal delay as static classes, so Tailwind can see them. */
    barClassName: string
    rate: string
    bad?: boolean
}): JSX.Element {
    return (
        <div className={cn('MCPHowItWorks__row', bad && 'MCPHowItWorks__row--bad')}>
            <b>{tool}</b>
            <span className="MCPHowItWorks__bar">
                <i className={barClassName} />
            </span>
            <span className="MCPHowItWorks__pct">
                {bad ? <IconWarning /> : null}
                {rate}
            </span>
        </div>
    )
}
