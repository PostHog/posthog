import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { EnrichedReviewer } from '../../types'
import { ReviewerClaim, reviewerClaimRemoveDisabledReason } from './SuggestedReviewerClaimControls'
import { SuggestedReviewerPerson } from './SuggestedReviewerPerson'
import { SuggestedReviewersList } from './SuggestedReviewersList'
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
                // The reviewer's name is the first tab stop because it opens the row menu.
                await userEvent.tab()
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
    test.each([
        ['a hover', async (tag: HTMLElement) => await userEvent.hover(tag)],
        [
            'keyboard focus',
            async (tag: HTMLElement) => {
                await userEvent.tab()
                await userEvent.tab()
                expect(tag).toHaveFocus()
            },
        ],
        ['a tap', async (tag: HTMLElement) => await userEvent.click(tag)],
    ])('keeps the reason in a hover card on the source tag and reveals it on %s', async (_case, reveal) => {
        const maya: EnrichedReviewer = {
            github_login: 'maya',
            github_name: 'Maya Rivera',
            relevant_commits: [],
            user: { id: 1, uuid: 'maya', first_name: 'Maya', last_name: 'Rivera', email: 'maya@example.com' },
            source_label: 'Code history',
            explanation: 'Recently changed the affected transport.',
        }

        render(<SuggestedReviewersList reviewers={[maya]} disabled={false} onRemove={() => undefined} />)

        const tag = screen.getByText('Code history')
        expect(screen.queryByText('Recently changed the affected transport.')).not.toBeInTheDocument()

        await reveal(tag)

        expect(await screen.findByText('Recently changed the affected transport.')).toBeInTheDocument()
    })
    it('keeps reviewer actions visible', async () => {
        const maya: EnrichedReviewer = {
            github_login: 'maya',
            github_name: 'Maya Rivera',
            relevant_commits: [],
            user: { id: 1, uuid: 'maya', first_name: 'Maya', last_name: 'Rivera', email: 'maya@example.com' },
            source_label: 'Code history',
            explanation: 'Recently changed the affected transport.',
        }
        const onRemove = jest.fn()

        render(<SuggestedReviewersSectionMockup suggestions={[maya]} onAdd={() => undefined} onRemove={onRemove} />)

        const reviewer = screen.getByText('Maya Rivera')
        const addButton = screen.getByText('Add')
        expect(addButton).toBeVisible()
        expect(addButton.compareDocumentPosition(reviewer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

        // The row shows no buttons. The name opens the reviewer's menu, and the picked reason travels with the removal.
        const row = screen.getByLabelText('Actions for Maya Rivera')
        expect(row).toBeVisible()
        await userEvent.click(row)
        await userEvent.click(await screen.findByText('Not their area'))
        expect(onRemove).toHaveBeenLastCalledWith([maya], { reason: 'wrong_area' })
        await userEvent.click(row)
        await userEvent.click(await screen.findByText('Without a reason'))
        expect(onRemove).toHaveBeenLastCalledWith([maya], undefined)
    })
    test.each([
        ['your own row while your claim is saving', 'me', true, 'Updating…'],
        ['your own row when no claim is saving', 'me', false, undefined],
        ["a teammate's row while your claim is saving", 'teammate', true, undefined],
    ])('removal of %s', (_case, uuid, saving, expected) => {
        const reviewer: EnrichedReviewer = {
            github_login: uuid,
            github_name: null,
            relevant_commits: [],
            user: { id: 1, uuid, first_name: 'Sam', last_name: 'Lee', email: 'sam@example.com' },
        }
        const claim: ReviewerClaim = {
            claimantUuid: null,
            currentUserUuid: 'me',
            claimable: true,
            saving,
            onSetClaimed: () => undefined,
        }

        expect(reviewerClaimRemoveDisabledReason(reviewer, claim, 'Sam Lee')).toEqual(expected)
    })
    it('shows a manual addition as its reason in place of the source tag', () => {
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

        expect(screen.getByText('Added by Avery Chen')).toBeVisible()
        expect(screen.queryByText('Added by teammate')).not.toBeInTheDocument()
    })
})
