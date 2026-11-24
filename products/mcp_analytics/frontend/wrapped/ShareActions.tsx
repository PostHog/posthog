import { useActions, useValues } from 'kea'
import { type RefObject, useState } from 'react'

import { IconCopy, IconDownload, IconShare } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { downloadBlob } from 'lib/components/ExportButton/exporter'

import { mcpWrappedLogic } from './mcpWrappedLogic'
import { canShareFiles, captureShareCard, copyShareCard, shareShareCard } from './shareImage'

const MCP_ANALYTICS_URL = 'https://posthog.com/mcp-analytics'

/** Share, copy and download for the share card. It sits under the card, so it is never part of the picture. */
export function ShareActions({ cardRef }: { cardRef: RefObject<HTMLDivElement> }): JSX.Element {
    const { wrapped } = useValues(mcpWrappedLogic)
    const { shareCaptured } = useActions(mcpWrappedLogic)
    const [busy, setBusy] = useState(false)
    const year = wrapped?.year ?? new Date().getFullYear()
    const fileName = `mcp-wrapped-${year}.png`
    const disabledReason = busy ? 'Creating the image' : undefined

    const share = async (): Promise<void> => {
        if (!cardRef.current) {
            return
        }
        setBusy(true)
        const outcome = await shareShareCard(
            cardRef.current,
            fileName,
            `My MCP server just got its ${year} Wrapped. Which personality is yours? ${MCP_ANALYTICS_URL}`
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
        <div className="mt-3 flex justify-center gap-2">
            {canShareFiles() && (
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconShare />}
                    onClick={() => void share()}
                    disabledReason={disabledReason}
                    data-attr="mcp-wrapped-share-native"
                >
                    Share
                </LemonButton>
            )}
            <LemonButton
                type={canShareFiles() ? 'secondary' : 'primary'}
                size="small"
                icon={<IconCopy />}
                onClick={() => void copy()}
                disabledReason={disabledReason}
                data-attr="mcp-wrapped-share-copy"
            >
                Copy image
            </LemonButton>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconDownload />}
                onClick={() => void download()}
                disabledReason={disabledReason}
                data-attr="mcp-wrapped-share-download"
            >
                Download
            </LemonButton>
        </div>
    )
}
