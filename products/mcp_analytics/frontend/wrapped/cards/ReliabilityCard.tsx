import { IconStar, IconWarning } from '@posthog/icons'

import type { MCPWrappedReliabilityCardApi } from '../../generated/api.schemas'
import { errorLine, formatPercent, formatSuccessRate, reliabilityLine } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

function ToolAward({
    label,
    icon,
    tool,
    stat,
    detail,
}: {
    label: string
    icon: JSX.Element
    tool: string
    stat: string
    detail: string
}): JSX.Element {
    return (
        <div className="MCPWrapped__rise flex flex-col gap-1.5">
            <span className="text-sm opacity-75">{label}</span>
            <div className="flex items-center gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-white text-black">
                    {icon}
                </span>
                <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate font-mono font-bold">{tool}</span>
                        <span className="shrink-0 font-bold tabular-nums">{stat}</span>
                    </div>
                    <div className="text-sm opacity-75">{detail}</div>
                </div>
            </div>
        </div>
    )
}

export function ReliabilityCard({ card }: { card: MCPWrappedReliabilityCardApi }): JSX.Element {
    const { most_reliable_tool: mvp, struggling_tool: struggling } = card
    return (
        <WrappedCard cardKey="reliability" kicker="Reliability">
            <div className="MCPWrapped__pop flex flex-wrap items-baseline gap-x-2">
                <span className="text-6xl font-bold leading-none tabular-nums">
                    {formatSuccessRate(card.success_rate)}
                </span>
                <span className="text-2xl font-bold">error-free</span>
            </div>
            <p className="MCPWrapped__rise m-0 text-base">
                <strong className="block">{reliabilityLine(card.success_rate)}</strong>
                {errorLine(card.success_rate)}
            </p>
            {(mvp || struggling) && (
                <div className="mt-2 flex flex-col gap-4">
                    {mvp && (
                        <ToolAward
                            label="Your MVP"
                            icon={<IconStar className="size-5" />}
                            tool={mvp.tool}
                            stat={`${formatSuccessRate(1 - mvp.error_rate)} success`}
                            detail={`Handled ${mvp.calls.toLocaleString('en-US')} calls like a champ.`}
                        />
                    )}
                    {struggling && (
                        <ToolAward
                            label="Needs some love"
                            icon={<IconWarning className="size-5" />}
                            tool={struggling.tool}
                            stat={`${formatPercent(struggling.error_rate)} errors`}
                            detail={`Had a few rough days across ${struggling.calls.toLocaleString('en-US')} calls.`}
                        />
                    )}
                </div>
            )}
        </WrappedCard>
    )
}
