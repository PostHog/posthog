import { useActions, useValues } from 'kea'
import { type RefObject, useEffect, useRef } from 'react'

import { IconPause, IconPlay, IconX } from '@posthog/icons'

import { teamLogic } from 'scenes/teamLogic'

import { ArchetypeCard } from './cards/ArchetypeCard'
import { IntroCard } from './cards/IntroCard'
import { ReliabilityCard } from './cards/ReliabilityCard'
import { RushHourCard } from './cards/RushHourCard'
import { ShareCard } from './cards/ShareCard'
import { SharesCard } from './cards/SharesCard'
import { SpeedCard } from './cards/SpeedCard'
import { ToolCallsCard } from './cards/ToolCallsCard'
import { TopToolsCard } from './cards/TopToolsCard'
import { CARD_DURATION_MS, mcpWrappedLogic } from './mcpWrappedLogic'
import { ShareActions } from './ShareActions'
import { WrappedCardKey } from './storyCards'

const CONTROL_CLASS =
    'flex size-7 items-center justify-center rounded-full bg-black/20 text-current hover:bg-black/30 outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-white'

function CurrentCard({
    cardKey,
    shareRef,
}: {
    cardKey: WrappedCardKey
    shareRef: RefObject<HTMLDivElement>
}): JSX.Element | null {
    const { wrapped } = useValues(mcpWrappedLogic)
    const { currentTeam } = useValues(teamLogic)
    if (!wrapped) {
        return null
    }
    const { cards, year } = wrapped
    const projectName = currentTeam?.name ?? 'Your project'
    switch (cardKey) {
        case 'intro':
            return <IntroCard card={cards.intro} projectName={projectName} year={year} />
        case 'tool_calls':
            return <ToolCallsCard card={cards.tool_calls} />
        case 'top_tools':
            return <TopToolsCard card={cards.top_tools} totalCalls={cards.tool_calls.total_calls} />
        case 'apps':
            return cards.apps ? (
                <SharesCard
                    cardKey="apps"
                    card={cards.apps}
                    kicker="The AI apps calling your server"
                    headline={(leader, share) => `${leader} led with ${share}`}
                    otherLabel="All other apps"
                />
            ) : null
        case 'labs':
            return cards.labs ? (
                <SharesCard
                    cardKey="labs"
                    card={cards.labs}
                    kicker="The AI labs behind the agents"
                    headline={(leader, share) => `${leader} models made ${share} of calls`}
                    otherLabel="Other labs"
                />
            ) : null
        case 'models':
            return cards.models ? (
                <SharesCard
                    cardKey="models"
                    card={cards.models}
                    kicker="The models doing the calling"
                    headline={(leader, share) => `${leader} led with ${share}`}
                    otherLabel="Other models"
                />
            ) : null
        case 'rush_hour':
            return cards.rush_hour ? <RushHourCard card={cards.rush_hour} /> : null
        case 'reliability':
            return <ReliabilityCard card={cards.reliability} />
        case 'speed':
            return cards.speed ? <SpeedCard card={cards.speed} /> : null
        case 'archetype':
            return <ArchetypeCard card={cards.archetype} />
        case 'share':
            return <ShareCard ref={shareRef} cards={cards} projectName={projectName} year={year} />
    }
}

export function WrappedStoryPlayer(): JSX.Element | null {
    const { cardKeys, cardIndex, currentCardKey, paused } = useValues(mcpWrappedLogic)
    const { nextCard, previousCard, setPaused, closeWrapped } = useActions(mcpWrappedLogic)
    const shareRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'ArrowRight') {
                nextCard()
            } else if (event.key === 'ArrowLeft') {
                previousCard()
            } else if (event.key === ' ') {
                event.preventDefault()
                setPaused(!paused)
            } else if (event.key === 'Escape') {
                closeWrapped()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [nextCard, previousCard, setPaused, closeWrapped, paused])

    if (!currentCardKey) {
        return null
    }

    return (
        <div className="mx-auto w-full max-w-sm">
            <div className="relative" aria-roledescription="story" data-attr="mcp-wrapped-story">
                <div key={currentCardKey}>
                    <CurrentCard cardKey={currentCardKey} shareRef={shareRef} />
                </div>
                <div className="absolute inset-x-3 top-3 z-10 flex gap-1">
                    {cardKeys.map((key, index) => (
                        <span key={key} className="h-[3px] flex-1 overflow-hidden rounded bg-white/35">
                            <span
                                className="block h-full bg-white"
                                style={
                                    index < cardIndex
                                        ? { width: '100%' }
                                        : index === cardIndex
                                          ? {
                                                width: '100%',
                                                transformOrigin: 'left',
                                                animation: `MCPWrapped__progress ${CARD_DURATION_MS}ms linear both`,
                                                animationPlayState: paused ? 'paused' : 'running',
                                            }
                                          : { width: 0 }
                                }
                            />
                        </span>
                    ))}
                </div>
                <div className="absolute inset-x-3.5 top-6 z-10 flex justify-end gap-1.5 text-white">
                    <button
                        type="button"
                        className={CONTROL_CLASS}
                        onClick={() => setPaused(!paused)}
                        aria-label={paused ? 'Play' : 'Pause'}
                        data-attr="mcp-wrapped-pause"
                    >
                        {paused ? <IconPlay /> : <IconPause />}
                    </button>
                    <button
                        type="button"
                        className={CONTROL_CLASS}
                        onClick={closeWrapped}
                        aria-label="Close"
                        data-attr="mcp-wrapped-close"
                    >
                        <IconX />
                    </button>
                </div>
                <button
                    type="button"
                    className="absolute bottom-0 left-0 top-16 z-[5] w-1/3 cursor-pointer bg-transparent outline-none focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-4 focus-visible:outline-white"
                    onClick={previousCard}
                    aria-label="Previous card"
                    data-attr="mcp-wrapped-previous"
                />
                <button
                    type="button"
                    className="absolute bottom-24 right-0 top-16 z-[5] w-2/3 cursor-pointer bg-transparent outline-none focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-4 focus-visible:outline-white"
                    onClick={nextCard}
                    aria-label="Next card"
                    data-attr="mcp-wrapped-next"
                />
            </div>
            {currentCardKey === 'share' && <ShareActions cardRef={shareRef} />}
        </div>
    )
}
