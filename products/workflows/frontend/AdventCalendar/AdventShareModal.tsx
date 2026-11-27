import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconCopy, IconDownload } from '@posthog/icons'
import { LemonButton, LemonModal, lemonToast } from '@posthog/lemon-ui'

import { captureElementAsImage, copyElementImageToClipboard } from 'lib/utils/copyImageToClipboard'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { downloadFile } from 'lib/utils/dom'

import { adventCalendarLogic } from './adventCalendarLogic'
import { ADVENT_LAST_DAY } from './adventContent'
import { AdventShareCard } from './AdventShareCard'

const SHARE_URL = 'https://app.posthog.com/workflows/advent'

export interface AdventShareModalProps {
    isOpen: boolean
    onClose: () => void
}

export function AdventShareModal({ isOpen, onClose }: AdventShareModalProps): JSX.Element {
    const { graph, openCount } = useValues(adventCalendarLogic)
    const { share } = useActions(adventCalendarLogic)
    const cardRef = useRef<HTMLDivElement>(null)
    const [busy, setBusy] = useState<'download' | 'copy' | null>(null)
    const text = `I opened ${openCount} of ${ADVENT_LAST_DAY} doors in the PostHog advent calendar.`

    const download = async (): Promise<void> => {
        if (!cardRef.current) {
            return
        }
        share()
        setBusy('download')
        try {
            const blob = await captureElementAsImage(cardRef.current)
            downloadFile(new File([blob], 'posthog-advent-calendar.png', { type: 'image/png' }))
        } catch {
            lemonToast.error("Couldn't create the image. Try again, or take a screenshot of the card.")
        } finally {
            setBusy(null)
        }
    }

    const copy = async (): Promise<void> => {
        if (!cardRef.current) {
            return
        }
        share()
        setBusy('copy')
        const { outcome } = await copyElementImageToClipboard(cardRef.current)
        setBusy(null)
        if (outcome === 'copied') {
            lemonToast.success('Image copied. Paste it into your post.')
        } else {
            lemonToast.error("Couldn't copy the image in this browser. Download it instead.")
        }
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={720}
            title="Share your calendar"
            description="Post about it, or add the picture of your village to a post."
            footer={
                <div className="flex w-full flex-wrap items-center justify-end gap-2">
                    <LemonButton
                        type="secondary"
                        targetBlank
                        data-attr="advent-share-linkedin"
                        onClick={() => share()}
                        to={`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(SHARE_URL)}`}
                    >
                        Post on LinkedIn
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        targetBlank
                        data-attr="advent-share-x"
                        onClick={() => share()}
                        to={`https://x.com/intent/post?text=${encodeURIComponent(text)}&url=${encodeURIComponent(SHARE_URL)}`}
                    >
                        Post on X
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        icon={<IconCopy />}
                        loading={busy === 'copy'}
                        disabledReason={busy ? 'Creating the image' : undefined}
                        data-attr="advent-share-copy"
                        onClick={() => void copy()}
                    >
                        Copy image
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        icon={<IconDownload />}
                        loading={busy === 'download'}
                        disabledReason={busy ? 'Creating the image' : undefined}
                        data-attr="advent-share-download"
                        onClick={() => void download()}
                    >
                        Download image
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        icon={<IconCopy />}
                        data-attr="advent-share-copy-link"
                        onClick={() => {
                            share()
                            void copyToClipboard(SHARE_URL, 'the link')
                        }}
                    >
                        Copy link
                    </LemonButton>
                </div>
            }
        >
            <div className="overflow-hidden rounded-lg border border-primary" data-attr="advent-share-preview">
                <AdventShareCard ref={cardRef} graph={graph} openCount={openCount} />
            </div>
        </LemonModal>
    )
}
