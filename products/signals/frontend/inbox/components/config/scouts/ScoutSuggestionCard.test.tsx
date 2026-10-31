import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'
import { mockAllIsIntersecting } from 'react-intersection-observer/test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mockScoutConfigs, mockScoutSuggestions, mockScoutSuggestionSet } from '../../../__mocks__/scoutConfigs'
import { INBOX_EVENTS } from '../../../inboxAnalytics'
import { scoutSuggestionsLogic } from '../../../logics/scoutSuggestionsLogic'
import { ScoutSuggestionCard } from './ScoutSuggestionCard'
import { ScoutSuggestionsStrip } from './ScoutSuggestionsStrip'

jest.mock('posthog-js')

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
        localStorage.clear()
        jest.mocked(posthog.get_distinct_id).mockReturnValue('test-user')
        jest.mocked(posthog.get_session_id).mockReturnValue('test-session')
        jest.spyOn(document, 'hidden', 'get').mockReturnValue(false)
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

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('requires half a card to remain visible for one second in the active tab', async () => {
        const logic = scoutSuggestionsLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.suggestionSet).not.toBeNull())
        await waitFor(() => expect(logic.values.scoutConfigs).not.toBeNull())
        const { unmount } = render(<ScoutSuggestionCard item={mockScoutSuggestions[1]} surface="strip" />)
        jest.useFakeTimers()
        jest.mocked(posthog.capture).mockClear()
        const impressions = (): unknown[] =>
            jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === INBOX_EVENTS.SCOUT_SUGGESTION_VIEWED)

        mockAllIsIntersecting(0.49)
        act(() => jest.advanceTimersByTime(1000))
        expect(impressions()).toHaveLength(0)

        mockAllIsIntersecting(0.5)
        act(() => jest.advanceTimersByTime(700))
        mockAllIsIntersecting(false)
        act(() => jest.advanceTimersByTime(1000))
        expect(impressions()).toHaveLength(0)

        mockAllIsIntersecting(0.5)
        act(() => jest.advanceTimersByTime(700))
        jest.spyOn(document, 'hidden', 'get').mockReturnValue(true)
        act(() => document.dispatchEvent(new Event('visibilitychange')))
        act(() => jest.advanceTimersByTime(1000))
        expect(impressions()).toHaveLength(0)

        jest.spyOn(document, 'hidden', 'get').mockReturnValue(false)
        act(() => document.dispatchEvent(new Event('visibilitychange')))
        act(() => jest.advanceTimersByTime(999))
        expect(impressions()).toHaveLength(0)
        act(() => jest.advanceTimersByTime(1))
        expect(impressions()).toHaveLength(1)

        mockAllIsIntersecting(false)
        mockAllIsIntersecting(0.5)
        act(() => jest.advanceTimersByTime(1000))
        expect(impressions()).toHaveLength(1)

        act(() =>
            logic.actions.loadSuggestionsSuccess(mockScoutSuggestionSet({ generated_at: '2026-09-02T00:00:00Z' }))
        )
        act(() => jest.advanceTimersByTime(500))
        unmount()
        act(() => jest.advanceTimersByTime(1000))
        expect(impressions()).toHaveLength(1)
        logic.unmount()
    })

    it('records cards after expansion and reopening, but never the collapsed strip', async () => {
        const logic = scoutSuggestionsLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.suggestionSet).not.toBeNull())
        await waitFor(() => expect(logic.values.scoutConfigs).not.toBeNull())
        const suggestionCount = logic.values.suggestions.length
        const { getByLabelText } = render(<ScoutSuggestionsStrip />)
        jest.useFakeTimers()
        jest.mocked(posthog.capture).mockClear()
        const impressions = (): unknown[] =>
            jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === INBOX_EVENTS.SCOUT_SUGGESTION_VIEWED)

        mockAllIsIntersecting(true)
        act(() => jest.advanceTimersByTime(1000))
        expect(impressions()).toHaveLength(0)

        fireEvent.click(getByLabelText('Show suggested scouts'))
        mockAllIsIntersecting(true)
        act(() => jest.advanceTimersByTime(1000))
        expect(impressions()).toHaveLength(suggestionCount)

        fireEvent.click(getByLabelText('Close suggested scouts'))
        act(() => logic.actions.showStrip())
        mockAllIsIntersecting(true)
        act(() => jest.advanceTimersByTime(1000))
        expect(impressions()).toHaveLength(suggestionCount)
        logic.unmount()
    })

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
