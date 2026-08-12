import { render, screen } from '@testing-library/react'

import { ScoutCreateModalSkeleton } from './ScoutCreateModalSkeleton'

describe('ScoutCreateModalSkeleton', () => {
    it('reserves the create modal while its form loads', () => {
        render(<ScoutCreateModalSkeleton />)

        expect(screen.getByText('Create a scout')).toBeTruthy()
        expect(screen.getByLabelText('Loading scout form')).toBeTruthy()
    })
})
