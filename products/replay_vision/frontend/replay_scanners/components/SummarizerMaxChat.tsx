import { useValues } from 'kea'

import { IconAI } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useMaxTool } from 'scenes/max/useMaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { replayScannerLogic } from '../replayScannerLogic'

/** PostHog AI entry point for summarizer scanners — lets the user chat about / digest the per-session summaries. */
export function SummarizerMaxChat({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const isSummarizer = scanner?.scanner_type === 'summarizer'

    const { openMax } = useMaxTool({
        identifier: 'summarize_replay_vision_summaries',
        active: isSummarizer && scannerId !== 'new',
        context: { scanner_id: scannerId },
        contextDescription: scanner
            ? { text: scanner.name || 'Summarizer scanner', icon: iconForType('session_replay') }
            : undefined,
        initialMaxPrompt: 'Find the common themes and patterns across these session summaries',
    })

    useAttachedContext(
        scannerId && scannerId !== 'new'
            ? [{ type: 'replay_vision_scanner', key: scannerId, label: scanner?.name ?? undefined }]
            : null,
        { active: isSummarizer && scannerId !== 'new' }
    )

    if (!openMax) {
        return null
    }

    return (
        <div className="border rounded p-4 bg-surface-primary flex items-center justify-between gap-4">
            <div>
                <h3 className="text-base font-semibold mb-1">Chat about these summaries</h3>
                <p className="text-sm text-muted m-0">
                    Ask PostHog AI to find themes and patterns across this scanner's session summaries.
                </p>
            </div>
            <LemonButton
                type="primary"
                icon={<IconAI />}
                onClick={() => openMax()}
                className="shrink-0"
                data-attr="vision-scanner-ask-ai"
            >
                Ask PostHog AI
            </LemonButton>
        </div>
    )
}
