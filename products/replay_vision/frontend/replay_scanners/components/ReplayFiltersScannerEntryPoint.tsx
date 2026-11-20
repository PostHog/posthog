import { LemonDivider } from '@posthog/lemon-ui'

import type { ScannerHandoffFromFilters } from '../scannerHandoffFromFilters'
import { ReplayFiltersScannerButton } from './ReplayFiltersScannerButton'

/** The Replay vision entry point in the replay filters footer. */
export function ReplayFiltersScannerEntryPoint({ handoff }: { handoff: ScannerHandoffFromFilters }): JSX.Element {
    return (
        <>
            <ReplayFiltersScannerButton handoff={handoff} />
            {/* Grouped away from the buttons that act on the filters themselves: this one leaves for another product. */}
            <LemonDivider vertical className="mx-1 self-stretch" />
        </>
    )
}
