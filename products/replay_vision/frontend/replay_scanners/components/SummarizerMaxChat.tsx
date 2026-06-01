import { useValues } from 'kea'

import { IconAI } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useMaxTool } from 'scenes/max/useMaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { replayScannerLogic } from '../replayScannerLogic'

/** "Ask Max" entry point for summarizer scanners — lets the user chat about / digest the per-session summaries. */
export function SummarizerMaxChat({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId, tabId }))
    const isSummarizer = scanner?.scanner_type === 'summarizer'

    const { openMax } = useMaxTool({
        identifier: 'summarize_replay_vision_summaries',
        active: isSummarizer && scannerId !== 'new',
        context: { scanner_id: scannerId },
        contextDescription: scanner
            ? { text: scanner.name || 'Summarizer scanner', icon: iconForType('session_replay') }
            : undefined,
        initialMaxPrompt: 'Summarize the session summaries from this scanner',
    })

    if (!openMax) {
        return null
    }

    return (
        <div className="border rounded p-4 bg-surface-primary flex items-center justify-between gap-4">
            <div>
                <h3 className="text-base font-semibold mb-1">Chat about these summaries</h3>
                <p className="text-sm text-muted m-0">
                    Ask Max to find themes and patterns across this scanner's session summaries.
                </p>
            </div>
            <LemonButton type="primary" icon={<IconAI />} onClick={() => openMax()} className="shrink-0">
                Ask Max
            </LemonButton>
        </div>
    )
}
