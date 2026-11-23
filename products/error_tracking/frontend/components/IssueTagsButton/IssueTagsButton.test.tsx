import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { IssueTagsButton } from './IssueTagsButton'

const TAGS = [
    { key: 'rule_checkout', label: 'Checkout' },
    { key: 'cause_in_trace', label: 'Cause in trace' },
]

describe('IssueTagsButton', () => {
    beforeEach(() => {
        useMocks({
            get: { '/api/projects/:team_id/error_tracking/tag_rules/': { results: [{ key: 'rule_checkout' }] } },
        })
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

    it('links only the tags that a rule applies to the tag rules settings', async () => {
        const user = userEvent.setup()
        const onTagClick = jest.fn()
        render(<IssueTagsButton tags={TAGS} onTagClick={onTagClick} />)

        await user.click(screen.getByText('2 tags'))
        const ruleLink = await screen.findByLabelText('Manage tag rules')

        expect(screen.getAllByLabelText('Manage tag rules')).toHaveLength(1)
        expect(ruleLink.closest('div')).toHaveTextContent('Checkout')
        expect(ruleLink).toHaveAttribute('href', expect.stringContaining('selectedSetting=error-tracking-tag-rules'))
        await user.click(ruleLink)
        expect(onTagClick).not.toHaveBeenCalled()
    })
})
