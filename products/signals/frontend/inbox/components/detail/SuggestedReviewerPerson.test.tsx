import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { EnrichedReviewer } from '../../types'
import { SuggestedReviewerPerson } from './SuggestedReviewerPerson'

describe('SuggestedReviewerPerson', () => {
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
})
