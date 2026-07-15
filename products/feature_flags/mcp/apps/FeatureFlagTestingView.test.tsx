import { cleanup, render, screen } from '@testing-library/react'
import { type ReactElement } from 'react'

import { type FeatureFlagTestingData, FeatureFlagTestingView } from './FeatureFlagTestingView'

// quill is a workspace package that isn't transformed under the frontend jest harness — stub it
// so this stays a unit test of FeatureFlagTestingView's own logic (matched-condition label + guard).
jest.mock(
    '@posthog/quill',
    () => ({
        Card: ({ children }: { children: ReactElement }) => <div>{children}</div>,
        CardHeader: ({ children }: { children: ReactElement }) => <div>{children}</div>,
        CardTitle: ({ children }: { children: ReactElement }) => <div>{children}</div>,
        CardDescription: ({ children }: { children: ReactElement }) => <div>{children}</div>,
        CardContent: ({ children }: { children: ReactElement }) => <div>{children}</div>,
        Badge: ({ children }: { children: ReactElement }) => <span>{children}</span>,
    }),
    { virtual: true }
)

const baseFlag: FeatureFlagTestingData = {
    flag_key: 'beta-feature',
    result: true,
    reason: 'condition_match',
    condition_index: 0,
    payload: null,
    person_properties: {},
    conditions: [],
}

describe('FeatureFlagTestingView', () => {
    afterEach(cleanup)

    const matchedConditionCases: Array<{ reason: string; condition_index: number | null; expectedLabel: string }> = [
        // The matcher always sets condition_index: Some(0) for an enrollment win.
        { reason: 'super_condition_value', condition_index: 0, expectedLabel: 'Early access enrollment' },
        // The matcher sets condition_index: None for a holdout win, which is why the guard also
        // has to check flag.reason directly, not just condition_index !== null.
        { reason: 'holdout_condition_value', condition_index: null, expectedLabel: 'Holdout' },
        { reason: 'condition_match', condition_index: 2, expectedLabel: '#3' },
    ]

    test.each(matchedConditionCases)(
        'labels the matched condition for reason $reason',
        ({ reason, condition_index, expectedLabel }) => {
            render(<FeatureFlagTestingView flag={{ ...baseFlag, reason, condition_index }} />)

            expect(screen.getByText('Matched condition:')).toBeTruthy()
            expect(screen.getByText(expectedLabel)).toBeTruthy()
        }
    )

    it('hides the matched-condition line when there is no condition index and no holdout', () => {
        render(<FeatureFlagTestingView flag={{ ...baseFlag, reason: 'no_condition_match', condition_index: null }} />)

        expect(screen.queryByText('Matched condition:')).toBeNull()
    })
})
