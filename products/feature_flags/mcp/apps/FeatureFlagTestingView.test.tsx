import { cleanup, render, screen } from '@testing-library/react'
import { type ReactElement } from 'react'

import {
    type ConditionAnalysis,
    type FeatureFlagTestingData,
    FeatureFlagTestingView,
    HOLDOUT_CONDITION_INDEX,
    SUPER_CONDITION_INDEX,
} from './FeatureFlagTestingView'

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

    const matchedConditionCases: Array<{
        reason: string
        condition_index: number | null
        conditions: ConditionAnalysis[]
        expectedLabel: string
    }> = [
        // The matcher always sets condition_index: Some(0) for an enrollment win, and the analysis
        // builder prepends a matched entry at the sentinel index — the label reads that entry.
        {
            reason: 'super_condition_value',
            condition_index: 0,
            conditions: [{ index: SUPER_CONDITION_INDEX, matched: true, rollout_percentage: 100 }],
            expectedLabel: 'Early access enrollment',
        },
        // The matcher sets condition_index: None for a holdout win, which is why the guard also
        // has to check flag.reason directly, not just condition_index !== null. The label reads
        // flag.reason since the matched entry sits at the holdout sentinel, not the enrollment one.
        {
            reason: 'holdout_condition_value',
            condition_index: null,
            conditions: [{ index: HOLDOUT_CONDITION_INDEX, matched: true, rollout_percentage: 100 }],
            expectedLabel: 'Holdout',
        },
        { reason: 'condition_match', condition_index: 2, conditions: [], expectedLabel: '#3' },
    ]

    test.each(matchedConditionCases)(
        'labels the matched condition for reason $reason',
        ({ reason, condition_index, conditions, expectedLabel }) => {
            render(<FeatureFlagTestingView flag={{ ...baseFlag, reason, condition_index, conditions }} />)

            expect(screen.getByText('Matched condition:')).toBeTruthy()
            expect(screen.getByText(expectedLabel)).toBeTruthy()
        }
    )

    it('derives the enrollment label from the matched condition entry, not flag.reason', () => {
        // reason deliberately disagrees with the conditions entry, so this only passes if the
        // label reads flag.conditions rather than re-checking flag.reason === 'super_condition_value'.
        render(
            <FeatureFlagTestingView
                flag={{
                    ...baseFlag,
                    reason: 'condition_match',
                    condition_index: 0,
                    conditions: [{ index: SUPER_CONDITION_INDEX, matched: true, rollout_percentage: 100 }],
                }}
            />
        )

        expect(screen.getByText('Early access enrollment')).toBeTruthy()
    })

    it('labels the holdout entry in the condition breakdown, not "Condition #-1"', () => {
        // A holdout win now carries a synthetic entry at the holdout sentinel index; the breakdown
        // must render it as "Holdout:" rather than deriving "Condition #<sentinel+1>" from the index.
        render(
            <FeatureFlagTestingView
                flag={{
                    ...baseFlag,
                    reason: 'holdout_condition_value',
                    condition_index: null,
                    conditions: [{ index: HOLDOUT_CONDITION_INDEX, matched: true, rollout_percentage: 100 }],
                }}
            />
        )

        expect(screen.getByText('Holdout:')).toBeTruthy()
        expect(screen.queryByText(`Condition #${HOLDOUT_CONDITION_INDEX + 1}:`)).toBeNull()
    })

    it('hides the matched-condition line when there is no condition index and no holdout', () => {
        render(<FeatureFlagTestingView flag={{ ...baseFlag, reason: 'no_condition_match', condition_index: null }} />)

        expect(screen.queryByText('Matched condition:')).toBeNull()
    })
})
