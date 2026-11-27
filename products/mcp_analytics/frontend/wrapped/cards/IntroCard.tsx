import type { MCPWrappedIntroCardApi } from '../../generated/api.schemas'
import { formatMonth } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { CARD_THEMES } from '../wrappedTheme'

/** The cover of the story: whose server it is, the year in big type, and the hedgehog that opens it. */
export function IntroCard({
    card,
    projectName,
    year,
}: {
    card: MCPWrappedIntroCardApi
    projectName: string
    year: number
}): JSX.Element {
    const plural = card.server_count > 1
    const Hoggie = CARD_THEMES.intro.hoggie
    return (
        <WrappedCard cardKey="intro" kicker="MCP Wrapped" hideHoggie>
            <div className="MCPWrapped__rise">
                <div className="text-2xl font-bold leading-tight">
                    {projectName}'s MCP {plural ? 'servers' : 'server'} in
                </div>
                <h2 className="m-0 text-8xl font-extrabold leading-none tracking-tight tabular-nums">{year}</h2>
            </div>
            <p className="MCPWrapped__rise m-0 text-base">
                Tracked with MCP analytics since{' '}
                <span className="MCPWrapped__mark">{formatMonth(card.tracked_since)}</span>. Here's how AI agents used{' '}
                {plural ? 'them' : 'it'}.
            </p>
            {/* The hedgehog takes the rest of the card, so the cover never has an empty half. */}
            <div className="MCPWrapped__pop relative flex min-h-0 flex-1 items-end justify-center">
                <span className="absolute bottom-[12%] size-56 rounded-full bg-white/20 blur-3xl" />
                <Hoggie className="MCPWrapped__hero-hoggie relative h-full max-h-72 w-auto" loading="eager" />
            </div>
        </WrappedCard>
    )
}
