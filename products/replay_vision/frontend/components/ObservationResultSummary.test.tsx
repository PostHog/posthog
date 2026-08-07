import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { ObservationStatusEnumApi, ReplayObservationApi } from '../generated/api.schemas'
import { ObservationResultSummary } from './ObservationCard'

function observation(status: ObservationStatusEnumApi, errorReason: string | null): ReplayObservationApi {
    return { status, error_reason: errorReason } as unknown as ReplayObservationApi
}

describe('ObservationResultSummary', () => {
    // Guards the fix for dead clicks on the observation Result column: failed and ineligible rows used to render a
    // bare em dash, hiding the reason the API returns in error_reason. A revert to the em dash fails these cases.
    const cases: [ObservationStatusEnumApi, string | null, string][] = [
        ['failed', 'validation_failed:model drifted', 'AI output did not fit the scanner'],
        ['ineligible', 'too_short:2s session', 'Too short'],
        ['failed', null, 'Scan failed'],
        ['ineligible', null, 'Skipped'],
    ]

    it.each(cases)('renders a %s label instead of an em dash', (status, errorReason, label) => {
        render(<ObservationResultSummary observation={observation(status, errorReason)} />)

        expect(screen.getByText(label)).toBeInTheDocument()
        expect(screen.queryByText('—')).not.toBeInTheDocument()
    })
})
