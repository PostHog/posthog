import type { ReplayObservationApi } from '../generated/api.schemas'
import { readResult } from './ObservationCard'
import { QuillObservationPrimaryOutput } from './QuillObservationPrimaryOutput'

export function QuillObservationResultSummary({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    if (
        observation.status === 'ineligible' ||
        observation.status === 'failed' ||
        !observation.scanner_snapshot ||
        !readResult(observation)
    ) {
        return <span className="text-muted-foreground text-sm">—</span>
    }
    return <QuillObservationPrimaryOutput observation={observation} compact showPrompt={false} reasoningTooltip />
}
