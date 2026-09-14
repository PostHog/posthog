import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mockScoutConfigs, mockScoutSuggestions, mockScoutSuggestionSet } from '../../../__mocks__/scoutConfigs'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { ScoutSuggestionCard } from './ScoutSuggestionCard'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

const mockGetAccessControlDisabledReason = getAccessControlDisabledReason as jest.MockedFunction<
    typeof getAccessControlDisabledReason
>

describe('ScoutSuggestionCard', () => {
    const canonicalItem = mockScoutSuggestions[0]
    let skillReads: number
    let releaseSkillRead: () => void

    beforeEach(() => {
        skillReads = 0
        mockGetAccessControlDisabledReason.mockReturnValue(null)
        const skillReadPending = new Promise<void>((resolve) => {
            releaseSkillRead = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team/signals/scout/configs/': [
                    { ...mockScoutConfigs[0], skill_name: canonicalItem.skill_name },
                ],
                '/api/projects/:team/signals/scout/suggestions/': mockScoutSuggestionSet(),
                // Held open by the test, so the card can be pressed again while the read is out.
                '/api/projects/:team/llm_skills/name/:name/': async () => {
                    skillReads += 1
                    await skillReadPending
                    return [
                        200,
                        {
                            name: canonicalItem.skill_name,
                            description: 'Watches web vitals.',
                            body: '# Web vitals\n\nCheck LCP on every run.',
                        },
                    ]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(cleanup)

    // A canonical press reads the scout over the network before the form opens. Without the busy
    // guard on the body, a second press repeats that read and reopens the form after it is closed.
    it('takes one press while the scout read is still out', async () => {
        const logic = scoutSuggestionsLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.scoutConfigs).not.toBeNull())
        const { getByTestId } = render(<ScoutSuggestionCard item={canonicalItem} surface="strip" />)

        const body = getByTestId('scout-suggestion-body') as HTMLButtonElement
        fireEvent.click(body)

        await waitFor(() => expect(skillReads).toBe(1))
        expect(body.disabled).toBe(true)

        fireEvent.click(body)
        releaseSkillRead()

        await waitFor(() => expect(logic.values.createFromSuggestion).not.toBeNull())
        expect(skillReads).toBe(1)
        logic.unmount()
    })

    // The body wraps the tags, the title and the motivation, so a name built from its children
    // leads with the "Turn on" tag while the press only opens the form.
    it.each([
        {
            kind: 'canonical',
            item: canonicalItem,
            label: 'Review scout: Watch web vitals on the pricing page',
        },
        {
            kind: 'custom',
            item: mockScoutSuggestions[1],
            label: 'Review draft: Watch signup drop-off by plan',
        },
    ])('names the card body after the form it opens on a $kind pick', ({ item, label }) => {
        const { getByLabelText, getByTestId } = render(<ScoutSuggestionCard item={item} surface="strip" />)

        expect(getByLabelText(label)).toBe(getByTestId('scout-suggestion-body'))
    })
})
