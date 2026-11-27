import { useActions, useValues } from 'kea'
import { type RefObject, useState } from 'react'

import { IconDownload } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { downloadBlob } from 'lib/components/ExportButton/exporter'

import { mcpWrappedLogic } from './mcpWrappedLogic'
import { captureShareCard } from './shareImage'

/** Downloads the share card as an image. It sits under the card, so it is never part of the picture. */
export function ShareActions({ cardRef }: { cardRef: RefObject<HTMLDivElement> }): JSX.Element {
    const { wrapped } = useValues(mcpWrappedLogic)
    const { shareCaptured } = useActions(mcpWrappedLogic)
    const [busy, setBusy] = useState(false)
    const year = wrapped?.year ?? new Date().getFullYear()

    const download = async (): Promise<void> => {
        if (!cardRef.current) {
            return
        }
        setBusy(true)
        try {
            downloadBlob(await captureShareCard(cardRef.current), `mcp-wrapped-${year}.png`)
            shareCaptured('download')
        } catch {
            lemonToast.error('Couldn’t create the image. Try again.')
        } finally {
            setBusy(false)
        }
    }

    return (
        <div className="mt-3 flex justify-center">
            <LemonButton
                type="primary"
                className="MCPWrapped__download"
                icon={<IconDownload />}
                onClick={() => void download()}
                loading={busy}
                data-attr="mcp-wrapped-share-download"
            >
                Download
            </LemonButton>
        </div>
    )
}
