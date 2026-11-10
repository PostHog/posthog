import './MCPHowItWorksAskStage.scss'

import { IconChat, IconSparkles, IconTerminal } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

export function MCPHowItWorksAskStage(): JSX.Element {
    return (
        <div className="MCPHowItWorks__chat">
            <div className="MCPHowItWorks__sources MCPHowItWorks__rv [--d:0s]">
                <span className="MCPHowItWorks__source">
                    <IconChat />
                    Slack
                </span>
                <span className="MCPHowItWorks__source">
                    <IconTerminal />
                    MCP client
                </span>
                <span className="MCPHowItWorks__source">
                    <IconSparkles />
                    PostHog AI
                </span>
            </div>
            <div className="MCPHowItWorks__bubble MCPHowItWorks__bubble--me MCPHowItWorks__rv [--d:0.4s]">
                Which tools are slowest?
            </div>
            <div className="MCPHowItWorks__reply">
                <div className="MCPHowItWorks__typing">
                    <span />
                    <span />
                    <span />
                </div>
                <div className="MCPHowItWorks__bubble MCPHowItWorks__bubble--ai MCPHowItWorks__rv [--d:2.4s]">
                    <div className="MCPHowItWorks__answer">
                        <IconSparkles />
                        <span>Here's a ranking by p95 latency over the last 30 days.</span>
                    </div>
                    <div className="MCPHowItWorks__table">
                        <div className="MCPHowItWorks__tr MCPHowItWorks__tr--head">
                            <span>Tool</span>
                            <span>Calls</span>
                            <span>Errors</span>
                            <span>p95</span>
                        </div>
                        <LatencyRow
                            tool="training_runs"
                            calls={122}
                            errors={31}
                            p95="287s"
                            delayClassName="[--d:2.8s]"
                        />
                        <LatencyRow tool="property_defs" calls={30} errors={1} p95="80s" delayClassName="[--d:3s]" />
                    </div>
                </div>
            </div>
        </div>
    )
}

function LatencyRow({
    tool,
    calls,
    errors,
    p95,
    delayClassName,
}: {
    tool: string
    calls: number
    errors: number
    p95: string
    delayClassName: string
}): JSX.Element {
    return (
        <div className={cn('MCPHowItWorks__tr MCPHowItWorks__rv', delayClassName)}>
            <b>{tool}</b>
            <span>{calls}</span>
            <span>{errors}</span>
            <span className="MCPHowItWorks__hi">{p95}</span>
        </div>
    )
}
