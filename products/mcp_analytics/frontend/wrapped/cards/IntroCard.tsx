import type { MCPWrappedIntroCardApi } from '../../generated/api.schemas'
import { formatMonth } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

export function IntroCard({
    card,
    projectName,
    year,
}: {
    card: MCPWrappedIntroCardApi
    projectName: string
    year: number
}): JSX.Element {
    const servers = card.server_count > 1 ? `, across ${card.server_count} servers` : ''
    return (
        <WrappedCard cardKey="intro" kicker={`MCP Wrapped · ${year}`}>
            <h2 className="MCPWrapped__rise m-0 text-4xl font-bold leading-tight">{projectName}'s year on MCP</h2>
            <p className="MCPWrapped__rise m-0 text-base">
                Tracked with MCP analytics since {formatMonth(card.tracked_since)}
                {servers}. Here's a look back.
            </p>
        </WrappedCard>
    )
}
