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
import { ARCHETYPE_HOGGIES } from '../wrappedTheme'
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

// Tool, app and model names can be long, and a versioned model id longer still. The picture has no
// tooltip, so a name wraps smaller instead of being cut off.
function valueClassName(tile: ShareTile): string {
    if (tile.kind === 'tool') {
        return cn(
            'line-clamp-3 font-mono [overflow-wrap:anywhere]',
            toolNameSize(tile.value, ['text-base', 'text-sm', 'text-xs'])
        )
    }
    if (tile.kind === 'app' || tile.kind === 'model') {
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
        const Hoggie = ARCHETYPE_HOGGIES[archetype]
        const tiles = shareTiles(cards)
        return (
            <WrappedCard ref={ref} cardKey="share" kicker={`MCP Wrapped ${year} · by PostHog`} hideHoggie>
                <div className="MCPWrapped__rise">
                    <div className="text-base opacity-75">
                        <strong>{projectName}</strong>'s MCP server is
                    </div>
                    <h2 className="m-0 text-4xl font-bold leading-tight">
                        <span className="MCPWrapped__highlight">{ARCHETYPE_NAMES[archetype]}</span>
                    </h2>
                </div>
                <div className="MCPWrapped__pop flex flex-col items-center gap-1 text-center">
                    <div className="relative flex justify-center">
                        <span className="absolute top-6 size-32 rounded-full bg-white/15 blur-2xl" />
                        <Hoggie className="MCPWrapped__hero-hoggie relative size-40" loading="eager" />
                    </div>
                    <p className="m-0 text-base font-bold">{ARCHETYPE_TAGLINES[archetype]}</p>
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
                                <dt className="text-xs opacity-60">{tile.label}</dt>
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
