import { useActions } from 'kea'
import { useRef, useState } from 'react'

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

const TILE_ICONS = {
    calls: IconTerminal,
    tool: IconWrench,
    reliability: IconCheckCircle,
    rush_hour: IconClock,
    speed: IconBolt,
} as const

function TileIcon({ tile }: { tile: ShareTile }): JSX.Element {
    if (tile.kind === 'app') {
        return <HarnessLogo category={tile.value} className="size-4" />
    }
    if (tile.kind === 'model') {
        return <BrandMark name={labMark(modelLab(tile.value))} className="size-4" />
    }
    const Icon = TILE_ICONS[tile.kind]
    return <Icon className="size-4" />
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
                <div className="text-sm font-bold opacity-75">{projectName}</div>
                <h2 className="m-0 text-4xl font-bold leading-tight">{ARCHETYPE_NAMES[archetype]}</h2>
            </div>
            <div className="MCPWrapped__pop flex flex-col items-center gap-1 text-center">
                <div className="relative flex justify-center">
                    <span className="absolute top-4 size-28 rounded-full bg-white/25 blur-2xl" />
                    <Hoggie className="MCPWrapped__hero-hoggie relative size-32" loading="eager" />
                </div>
                <p className="m-0 text-base font-bold">{ARCHETYPE_TAGLINES[archetype]}</p>
            </div>
            <div className="MCPWrapped__rise grid grid-cols-2 gap-2">
                {tiles.map((tile, index) => (
                    <div
                        key={tile.label}
                        className={cn(
                            'flex min-w-0 items-center gap-2 rounded-xl bg-white/15 p-2.5',
                            // An odd tile out spans the row, so the grid stays balanced when data is missing.
                            tiles.length % 2 === 1 && index === tiles.length - 1 && 'col-span-2'
                        )}
                    >
                        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-white text-black">
                            <TileIcon tile={tile} />
                        </span>
                        <span className="min-w-0">
                            <span className="block text-xs opacity-75">{tile.label}</span>
                            <span
                                className={cn('block truncate text-sm font-bold', tile.kind === 'tool' && 'font-mono')}
                                title={tile.value}
                            >
                                {tile.value}
                            </span>
                        </span>
                    </div>
                ))}
            </div>
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
                className="MCPWrapped__rise mt-auto flex items-center justify-center gap-2 text-current no-underline"
                data-attr="mcp-wrapped-share-plug"
            >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-white text-black">
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
