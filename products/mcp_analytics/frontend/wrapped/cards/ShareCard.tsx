import { useActions } from 'kea'
import { useRef, useState } from 'react'

import { IconBolt, IconCheckCircle, IconClock, IconLogomark, IconTerminal, IconWrench } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { BrandMark } from 'lib/components/BrandMark/BrandMark'
import { downloadBlob } from 'lib/components/ExportButton/exporter'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { captureElementAsPng, copyElementImageToClipboard } from 'lib/utils/copyImageToClipboard'

import { labMark, modelLab } from '../../aiLabs'
import { HarnessLogo } from '../../dashboard/harness'
import type { MCPWrappedCardsApi } from '../../generated/api.schemas'
import { mcpWrappedLogic } from '../mcpWrappedLogic'
import { ARCHETYPE_NAMES, ARCHETYPE_TAGLINES, type ShareTile, shareTiles } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

const ACTIONS_CLASS = 'MCPWrapped__share-actions'
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

    const copy = async (): Promise<void> => {
        if (!cardRef.current) {
            return
        }
        setBusy(true)
        const result = await copyElementImageToClipboard(cardRef.current, `.${ACTIONS_CLASS}`)
        setBusy(false)
        if (result.outcome === 'copied') {
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
            const blob = await captureElementAsPng(cardRef.current, `.${ACTIONS_CLASS}`)
            downloadBlob(blob, `mcp-wrapped-${year}.png`)
            shareCaptured('download')
        } catch {
            lemonToast.error('Couldn’t create the image. Try again.')
        } finally {
            setBusy(false)
        }
    }

    return (
        <WrappedCard ref={cardRef} cardKey="share" kicker={`${projectName} · MCP Wrapped ${year}`}>
            <div className="MCPWrapped__rise">
                <h2 className="m-0 text-4xl font-bold leading-tight">{ARCHETYPE_NAMES[cards.archetype.archetype]}</h2>
                <p className="m-0 text-base font-bold">{ARCHETYPE_TAGLINES[cards.archetype.archetype]}</p>
            </div>
            <div className="MCPWrapped__rise grid grid-cols-2 gap-2">
                {shareTiles(cards).map((tile) => (
                    <div key={tile.label} className="flex min-w-0 items-center gap-2 rounded-xl bg-white/15 p-2.5">
                        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-white text-black">
                            <TileIcon tile={tile} />
                        </span>
                        <span className="min-w-0">
                            <span className="block text-xs opacity-75">{tile.label}</span>
                            <span className="block truncate text-sm font-bold" title={tile.value}>
                                {tile.value}
                            </span>
                        </span>
                    </div>
                ))}
            </div>
            <div className={`${ACTIONS_CLASS} flex gap-2`}>
                <LemonButton
                    type="primary"
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
                className="MCPWrapped__rise mt-auto flex max-w-[60%] items-center gap-2 text-current no-underline"
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
