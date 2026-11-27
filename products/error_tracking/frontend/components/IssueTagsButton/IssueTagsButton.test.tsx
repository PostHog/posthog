import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { IssueTagsButton } from './IssueTagsButton'

const TAGS = [
    { key: 'rule_checkout', label: 'Checkout' },
    { key: 'cause_in_trace', label: 'Cause in trace' },
]

describe('IssueTagsButton', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([[[]], [null]])('shows no button for an issue with tags %p', (tags) => {
        const { container } = render(<IssueTagsButton tags={tags} onTagClick={jest.fn()} />)

        expect(container).toBeEmptyDOMElement()
    })

    it('sends the key of the tag clicked in the list, then closes the list', async () => {
        const user = userEvent.setup()
        const onTagClick = jest.fn()
        render(<IssueTagsButton tags={TAGS} onTagClick={onTagClick} />)

        await user.click(screen.getByText('2 tags'))
        await user.click(await screen.findByLabelText('Show issues tagged Cause in trace'))

        expect(onTagClick).toHaveBeenCalledWith('cause_in_trace')
        await waitFor(() => expect(screen.queryByLabelText('Issue tags')).not.toBeInTheDocument())
    })

    it('links to the tag rules settings without filtering by a tag', async () => {
        const user = userEvent.setup()
        const onTagClick = jest.fn()
        render(<IssueTagsButton tags={TAGS} onTagClick={onTagClick} />)

        await user.click(screen.getByText('2 tags'))
        const rulesLink = await screen.findByText('Manage tag rules')

        expect(rulesLink.closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining('selectedSetting=error-tracking-tag-rules')
        )
        await user.click(rulesLink)
        expect(onTagClick).not.toHaveBeenCalled()
    })
})
