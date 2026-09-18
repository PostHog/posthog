import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { EnrichedReviewer } from '../../types'
import { SuggestedReviewerPerson } from './SuggestedReviewerPerson'

describe('SuggestedReviewerPerson', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('keeps a scout name in the source tooltip', async () => {
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

        expect(screen.getByText('Added by scout')).toBeInTheDocument()
        expect(screen.queryByText(scoutName)).not.toBeInTheDocument()

        await userEvent.hover(screen.getByText('Added by scout'))
        expect(await screen.findByText(scoutName)).toBeInTheDocument()
    })
})
