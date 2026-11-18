import type { MCPWrappedSpeedCardApi, MCPWrappedToolLatencyApi } from '../../generated/api.schemas'
import { formatDuration } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

function ToolLatency({ label, tool }: { label: string; tool: MCPWrappedToolLatencyApi }): JSX.Element {
    return (
        <div className="rounded-xl bg-white/10 p-2.5">
            <div className="font-mono text-[10px] font-semibold uppercase opacity-75">{label}</div>
            <div className="break-all font-mono text-base font-bold">{tool.tool}</div>
            <div className="font-mono text-[10px] uppercase opacity-75">p95 {formatDuration(tool.p95_duration_ms)}</div>
        </div>
    )
}

export function SpeedCard({ card }: { card: MCPWrappedSpeedCardApi }): JSX.Element {
    return (
        <WrappedCard cardKey="speed" kicker="Response times">
            <div className="MCPWrapped__pop text-6xl font-bold leading-none">
                {formatDuration(card.p95_duration_ms)}
            </div>
            <p className="MCPWrapped__rise m-0 text-base">95% of tool calls returned faster than this.</p>
            <div className="MCPWrapped__rise flex flex-col gap-2.5">
                {card.quickest_busy_tool && <ToolLatency label="Fastest busy tool" tool={card.quickest_busy_tool} />}
                {card.slowest_tool && <ToolLatency label="Slowest tool" tool={card.slowest_tool} />}
            </div>
        </WrappedCard>
    )
}
