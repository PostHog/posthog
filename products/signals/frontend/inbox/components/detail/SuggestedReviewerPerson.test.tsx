import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { EnrichedReviewer } from '../../types'
import { SuggestedReviewerPerson } from './SuggestedReviewerPerson'
import { SuggestedReviewersSectionMockup } from './SuggestedReviewersSectionMockup'

describe('Suggested reviewer presentation', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    test.each([
        ['a hover', async (tag: HTMLElement) => await userEvent.hover(tag)],
        [
            'keyboard focus',
            async (tag: HTMLElement) => {
                await userEvent.tab()
                expect(tag).toHaveFocus()
            },
        ],
    ])('reveals a scout name in the source tooltip on %s', async (_case, reveal) => {
        const scoutName = 'Infrastructure reliability and request processing ownership scout'
        const reviewer: EnrichedReviewer = {
            github_login: 'solo',
            user_uuid: 'solo',
            github_name: 'Solo Scout',
            relevant_commits: [],
            user: {
                id: 1,
                uuid: 'solo',
                first_name: 'Solo',
                last_name: 'Scout',
                email: 'solo@example.com',
            },
            source_skill: 'signals-scout-infrastructure-reliability',
            source_label: scoutName,
            explanation: 'Maintains the request path.',
        }

        render(<SuggestedReviewerPerson reviewer={reviewer} disabled={false} onRemove={() => undefined} />)

        const tag = screen.getByText('Added by scout')
        expect(tag).toBeInTheDocument()
        expect(screen.queryByText(scoutName)).not.toBeInTheDocument()

        await reveal(tag)

        expect(await screen.findByText(scoutName)).toBeInTheDocument()
    })
    it('shows each reason before its indented reviewer and keeps actions visible', async () => {
        const maya: EnrichedReviewer = {
            github_login: 'maya',
            github_name: 'Maya Rivera',
            relevant_commits: [],
            user: { id: 1, uuid: 'maya', first_name: 'Maya', last_name: 'Rivera', email: 'maya@example.com' },
            source_label: 'Code history',
            explanation: 'Recently changed the affected transport.',
        }
        const quinn: EnrichedReviewer = {
            ...maya,
            github_login: 'quinn',
            github_name: 'Quinn Foster',
            user: { id: 2, uuid: 'quinn', first_name: 'Quinn', last_name: 'Foster', email: 'quinn@example.com' },
            source_skill: null,
            source_label: 'Added by teammate',
            reason: 'Added as a reviewer by Avery Chen on Jan 1, 2026',
            explanation: null,
        }
        const onRemove = jest.fn()

        render(
            <SuggestedReviewersSectionMockup suggestions={[maya, quinn]} onAdd={() => undefined} onRemove={onRemove} />
        )

        const reason = screen.getByText('Recently changed the affected transport.')
        const reviewer = screen.getByText('Maya Rivera')
        expect(reason.compareDocumentPosition(reviewer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(reviewer.closest('.pl-3')).toBeInTheDocument()
        expect(screen.getByText('Quinn Foster').closest('.pl-3')).not.toBeInTheDocument()
        const addButton = screen.getByRole('button', { name: 'Add Reviewer' })
        expect(addButton).toBeVisible()
        expect(
            screen.getByText('Quinn Foster').compareDocumentPosition(addButton) & Node.DOCUMENT_POSITION_FOLLOWING
        ).toBeTruthy()

        const removeButton = screen.getByRole('button', { name: 'Remove Maya Rivera' })
        expect(removeButton).toBeVisible()
        expect(removeButton).not.toHaveClass('opacity-0')
        await userEvent.click(removeButton)
        expect(onRemove).toHaveBeenCalledWith([maya])
    })
    it('shows a manual addition as a reason without a source badge', () => {
        const quinn: EnrichedReviewer = {
            github_login: 'quinn',
            github_name: 'Quinn Foster',
            relevant_commits: [],
            user: { id: 2, uuid: 'quinn', first_name: 'Quinn', last_name: 'Foster', email: 'quinn@example.com' },
            source_skill: null,
            source_label: 'Added by teammate',
            reason: 'Added as a reviewer by Avery Chen on Jan 1, 2026',
            explanation: 'Added by Avery Chen',
        }

        render(
            <SuggestedReviewersSectionMockup suggestions={[quinn]} onAdd={() => undefined} onRemove={() => undefined} />
        )

        const reason = screen.getByText('Added by Avery Chen')
        const reviewer = screen.getByText('Quinn Foster')
        expect(reason.compareDocumentPosition(reviewer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(reviewer.closest('.pl-3')).toBeInTheDocument()
        expect(screen.queryByText('Added by teammate')).not.toBeInTheDocument()
    })
})
