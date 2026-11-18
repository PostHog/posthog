import { useActions } from 'kea'
import { useRef, useState } from 'react'

import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { downloadBlob } from 'lib/components/ExportButton/exporter'
import { captureElementAsPng, copyElementImageToClipboard } from 'lib/utils/copyImageToClipboard'

import type { MCPWrappedCardsApi } from '../../generated/api.schemas'
import { mcpWrappedLogic } from '../mcpWrappedLogic'
import { ARCHETYPE_NAMES, shareTiles } from '../storyCards'
import { WrappedCard } from '../WrappedCard'

const ACTIONS_CLASS = 'MCPWrapped__share-actions'

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
            <h2 className="MCPWrapped__rise m-0 text-3xl font-bold leading-tight">
                {ARCHETYPE_NAMES[cards.archetype.archetype]}
            </h2>
            <div className="MCPWrapped__rise grid grid-cols-2 gap-2.5">
                {shareTiles(cards).map((tile) => (
                    <div key={tile.label} className="min-w-0 rounded-xl bg-white/15 p-2.5">
                        <div className="font-mono text-[10px] font-semibold uppercase opacity-80">{tile.label}</div>
                        <div className="truncate text-lg font-bold">{tile.value}</div>
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
        </WrappedCard>
    )
}
