import { useActions } from 'kea'
import { useRef, useState } from 'react'

import { colors } from '@posthog/brand/colors'
import { IconBolt, IconCheckCircle, IconClock, IconLogomark, IconTerminal, IconWrench } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { downloadBlob } from 'lib/components/ExportButton/exporter'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'

import { labMark, modelLab } from '../../aiLabs'
import { HarnessLogo } from '../../dashboard/harness'
import type { MCPWrappedCardsApi } from '../../generated/api.schemas'
import { mcpWrappedLogic } from '../mcpWrappedLogic'
import { canShareFiles, captureShareCard, copyShareCard, SHARE_ACTIONS_CLASS, shareShareCard } from '../shareImage'
import { ARCHETYPE_NAMES, ARCHETYPE_TAGLINES, type ShareTile, shareTiles } from '../storyCards'
import { WrappedCard } from '../WrappedCard'
import { ARCHETYPE_HOGGIES } from '../wrappedTheme'

const MCP_ANALYTICS_URL = 'https://posthog.com/mcp-analytics'

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
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-white shadow-sm">
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

export function ShareCard({
    cards,
    projectName,
    year,
}: {
    cards: MCPWrappedCardsApi
    projectName: string
    year: number
}): JSX.Element {
    const { shareCaptured } = useActions(mcpWrappedLogic)
    const cardRef = useRef<HTMLDivElement>(null)
    const [busy, setBusy] = useState(false)
    const { archetype } = cards.archetype
    const Hoggie = ARCHETYPE_HOGGIES[archetype]
    const tiles = shareTiles(cards)
    const fileName = `mcp-wrapped-${year}.png`

    const share = async (): Promise<void> => {
        if (!cardRef.current) {
            return
        }
        setBusy(true)
        const outcome = await shareShareCard(
            cardRef.current,
            fileName,
            `My MCP server just got its ${year} Wrapped. ${MCP_ANALYTICS_URL}`
        )
        setBusy(false)
        if (outcome === 'done') {
            shareCaptured('share')
        } else if (outcome !== 'cancelled') {
            lemonToast.error('Couldn’t share the image. Try Download instead.')
        }
    }

    const copy = async (): Promise<void> => {
        if (!cardRef.current) {
            return
        }
        setBusy(true)
        const outcome = await copyShareCard(cardRef.current)
        setBusy(false)
        if (outcome === 'done') {
            lemonToast.success('Image copied')
            shareCaptured('copy')
        } else {
            lemonToast.error('Couldn’t copy the image. Try Download instead.')
        }
    }

    const download = async (): Promise<void> => {
        if (!cardRef.current) {
            return
        }
        setBusy(true)
        try {
            downloadBlob(await captureShareCard(cardRef.current), fileName)
            shareCaptured('download')
        } catch {
            lemonToast.error('Couldn’t create the image. Try again.')
        } finally {
            setBusy(false)
        }
    }

    return (
        <WrappedCard ref={cardRef} cardKey="share" kicker={`MCP Wrapped · ${year}`} hideHoggie>
            <div className="MCPWrapped__rise">
                <div className="text-sm opacity-75">
                    How AI agents used <strong>{projectName}</strong>'s MCP server
                </div>
                <h2 className="m-0 text-4xl font-bold leading-tight">
                    <span className="MCPWrapped__highlight">{ARCHETYPE_NAMES[archetype]}</span>
                </h2>
            </div>
            <div className="MCPWrapped__pop flex flex-col items-center gap-1 text-center">
                <div className="relative flex justify-center">
                    <span className="absolute top-4 size-28 rounded-full bg-white/25 blur-2xl" />
                    <Hoggie className="MCPWrapped__hero-hoggie relative size-32" loading="eager" />
                </div>
                <p className="m-0 text-base font-bold">{ARCHETYPE_TAGLINES[archetype]}</p>
            </div>
            <dl className="MCPWrapped__rise m-0 grid grid-cols-2 gap-x-5">
                {tiles.map((tile, index) => (
                    <div
                        key={tile.label}
                        className={cn(
                            'flex min-w-0 items-center gap-2.5 border-t border-black/10 py-2',
                            // An odd stat out spans the row, so the list stays balanced when data is missing.
                            tiles.length % 2 === 1 && index === tiles.length - 1 && 'col-span-2'
                        )}
                    >
                        <StatIcon tile={tile} />
                        <div className="min-w-0">
                            <dt className="text-xs opacity-60">{tile.label}</dt>
                            <dd
                                className={cn('m-0 truncate text-base font-bold', tile.kind === 'tool' && 'font-mono')}
                                title={tile.value}
                            >
                                {tile.value}
                            </dd>
                        </div>
                    </div>
                ))}
            </dl>
            <div className={`${SHARE_ACTIONS_CLASS} flex gap-2`}>
                {canShareFiles() && (
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={() => void share()}
                        disabledReason={busy ? 'Creating the image' : undefined}
                        data-attr="mcp-wrapped-share-native"
                    >
                        Share
                    </LemonButton>
                )}
                <LemonButton
                    type={canShareFiles() ? 'secondary' : 'primary'}
                    size="small"
                    onClick={() => void copy()}
                    disabledReason={busy ? 'Creating the image' : undefined}
                    data-attr="mcp-wrapped-share-copy"
                >
                    Copy image
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => void download()}
                    disabledReason={busy ? 'Creating the image' : undefined}
                    data-attr="mcp-wrapped-share-download"
                >
                    Download
                </LemonButton>
            </div>
            <LinkPrimitive
                to={MCP_ANALYTICS_URL}
                target="_blank"
                className="MCPWrapped__rise mt-auto flex items-center justify-center gap-2 border-t-2 border-dashed border-black/15 pt-3 text-current no-underline"
                data-attr="mcp-wrapped-share-plug"
            >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-black text-white">
                    <IconLogomark className="size-5" />
                </span>
                <span className="text-xs leading-tight">
                    <span className="block font-bold">Made with PostHog MCP analytics</span>
                    <span className="opacity-75">posthog.com/mcp-analytics</span>
                </span>
            </LinkPrimitive>
        </WrappedCard>
    )
}
