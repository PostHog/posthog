import { forwardRef } from 'react'

import { colors } from '@posthog/brand/colors'
import { IconBolt, IconCheckCircle, IconClock, IconTerminal, IconWrench } from '@posthog/icons'

import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { cn } from 'lib/utils/css-classes'

import { labMark, modelLab } from '../../aiLabs'
import { HarnessLogo } from '../../dashboard/harness'
import type { MCPWrappedCardsApi } from '../../generated/api.schemas'
import {
    ARCHETYPE_NAMES,
    ARCHETYPE_TAGLINES,
    type ShareTile,
    shareTiles,
    toolNameSize,
    wrappableToolName,
} from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { shareTheme } from '../wrappedTheme'
import { SharePlug } from './SharePlug'

// Each number gets its own brand colour, so the list reads like a poster rather than a table.
const STAT_ICONS = {
    calls: { Icon: IconTerminal, color: colors.tangerine.core },
    tool: { Icon: IconWrench, color: colors.cobalt.core },
    reliability: { Icon: IconCheckCircle, color: colors.green.darker },
    rush_hour: { Icon: IconClock, color: colors.yellow.core },
    speed: { Icon: IconBolt, color: colors.violet.core },
} as const

function StatIcon({ tile }: { tile: ShareTile }): JSX.Element {
    if (tile.kind === 'app' || tile.kind === 'model') {
        return (
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-white text-black">
                {tile.kind === 'app' ? (
                    <HarnessLogo category={tile.value} className="size-3.5" />
                ) : (
                    <BrandMark name={labMark(modelLab(tile.value))} className="size-3.5" />
                )}
            </span>
        )
    }
    const { Icon, color } = STAT_ICONS[tile.kind]
    return (
        <span
            className="flex size-6 shrink-0 items-center justify-center rounded-full text-white"
            style={{ background: color }}
        >
            <Icon className="size-3.5" />
        </span>
    )
}

// Tool, app and model names can be long, a versioned model id longer still, and "Wednesday 12 pm" is wider
// than its tile. The picture has no tooltip, so a value wraps instead of being cut off.
function valueClassName(tile: ShareTile): string {
    if (tile.kind === 'tool') {
        return cn(
            'line-clamp-3 font-mono [overflow-wrap:anywhere]',
            toolNameSize(tile.value, ['text-base', 'text-sm', 'text-xs'])
        )
    }
    if (tile.kind === 'app' || tile.kind === 'model' || tile.kind === 'rush_hour') {
        return cn(
            'line-clamp-2 [overflow-wrap:anywhere]',
            toolNameSize(tile.value, ['text-base', 'text-base', 'text-sm'])
        )
    }
    return 'truncate text-base'
}

/** The poster at the end of the story, which the share actions turn into an image. */
export const ShareCard = forwardRef<HTMLDivElement, { cards: MCPWrappedCardsApi; projectName: string; year: number }>(
    function ShareCard({ cards, projectName, year }, ref): JSX.Element {
        const { archetype } = cards.archetype
        const theme = shareTheme(archetype)
        const Hoggie = theme.hoggie
        const tiles = shareTiles(cards)
        return (
            <WrappedCard ref={ref} cardKey="share" kicker="MCP Wrapped · by PostHog" theme={theme} hideHoggie>
                <h2 className="MCPWrapped__rise m-0 text-2xl font-bold leading-tight [overflow-wrap:anywhere]">
                    {projectName}'s MCP {cards.intro.server_count > 1 ? 'servers' : 'server'} in{' '}
                    {year}
                </h2>
                {/* The hedgehog takes the space the title and stats leave, so a long project or tool name shrinks
                    it rather than pushing the stats off the poster. */}
                <div className="MCPWrapped__pop flex min-h-0 flex-1 flex-col items-center gap-1 text-center">
                    <div className="relative flex min-h-0 flex-1 items-end justify-center">
                        <span className="absolute bottom-[10%] size-32 rounded-full bg-white/15 blur-2xl" />
                        <Hoggie className="MCPWrapped__hero-hoggie relative h-full max-h-40 w-auto" loading="eager" />
                    </div>
                    <p className="m-0 text-3xl font-bold leading-tight">{ARCHETYPE_NAMES[archetype]}</p>
                    <p className="m-0 text-sm opacity-75">{ARCHETYPE_TAGLINES[archetype]}</p>
                </div>
                <dl className="MCPWrapped__rise m-0 grid grid-cols-2 gap-x-5">
                    {tiles.map((tile, index) => (
                        <div
                            key={tile.label}
                            className={cn(
                                'flex min-w-0 items-center gap-2.5 border-t border-white/10 py-2.5',
                                // An odd stat out spans the row, so the list stays balanced when data is missing.
                                tiles.length % 2 === 1 && index === tiles.length - 1 && 'col-span-2'
                            )}
                        >
                            <StatIcon tile={tile} />
                            <div className="min-w-0">
                                <dt className="text-xs opacity-75">{tile.label}</dt>
                                <dd className={cn('m-0 font-bold', valueClassName(tile))} title={tile.value}>
                                    {tile.kind === 'tool' ? wrappableToolName(tile.value) : tile.value}
                                </dd>
                            </div>
                        </div>
                    ))}
                </dl>
                <SharePlug />
            </WrappedCard>
        )
    }
)
