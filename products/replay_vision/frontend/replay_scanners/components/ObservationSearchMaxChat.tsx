import { useValues } from 'kea'

import { IconAI } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useMaxTool } from 'scenes/max/useMaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { replayScannerLogic } from '../replayScannerLogic'

/** A scanner-type-specific example question, shown in the copy and prefilled into Max when the user opens it. */
function exampleQuestion(scannerType?: string): string {
    switch (scannerType) {
        case 'monitor':
            return 'What are common trends across sessions that resulted in "yes"?'
        case 'classifier':
            return 'What are the common themes across sessions tagged "frustrated"?'
        case 'scorer':
            return "What's driving the lowest-scoring sessions?"
        default:
            return 'What stands out across these sessions?'
    }
}

/** PostHog AI entry point for any scanner type — lets the user search this scanner's observations by the meaning of their model reasoning. */
export function ObservationSearchMaxChat({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const example = exampleQuestion(scanner?.scanner_type)

    const { openMax } = useMaxTool({
        identifier: 'search_replay_vision_observations',
        active: scannerId !== 'new',
        context: { scanner_id: scannerId },
        contextDescription: scanner
            ? { text: scanner.name || 'Replay Vision scanner', icon: iconForType('session_replay') }
            : undefined,
        initialMaxPrompt: example,
    })

    // Summarizer scanners already surface their own "Chat about these summaries" entry point; keep the search
    // tool registered for Max, but don't render a second, near-identical card on that page.
    if (!openMax || scanner?.scanner_type === 'summarizer') {
        return null
    }

    return (
        <div className="border rounded p-4 bg-surface-primary flex items-center justify-between gap-4">
            <div>
                <h3 className="text-base font-semibold mb-1">Chat about these sessions</h3>
                <p className="text-sm text-muted m-0">
                    Ask PostHog AI about this scanner's sessions and results. For example, "{example}"
                </p>
            </div>
            <LemonButton
                type="primary"
                icon={<IconAI />}
                onClick={() => openMax()}
                className="shrink-0"
                data-attr="vision-scanner-search-ai"
            >
                Ask PostHog AI
            </LemonButton>
        </div>
    )
}
