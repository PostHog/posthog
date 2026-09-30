import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { IssueStatusSelect } from './IssueStatusSelect'

describe('IssueStatusSelect', () => {
    it('updates the issue status from the menu', async () => {
        const user = userEvent.setup()
        const onChange = jest.fn()
        render(<IssueStatusSelect status="active" onChange={onChange} />)

        await user.click(screen.getByLabelText('Status: Active'))
        await user.click(await screen.findByText('Resolved'))

        expect(onChange).toHaveBeenCalledWith('resolved')
    })
})
