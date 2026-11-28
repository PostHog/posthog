import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import posthog from 'posthog-js'

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
        const { container } = render(<IssueTagsButton tags={tags} onTagClick={jest.fn()} surface="issues_list" />)

        expect(container).toBeEmptyDOMElement()
    })

    it('shows one circle per distinct tag color on the button, at most three', () => {
        const tags = (['blue', 'blue', 'teal', 'red', 'green'] as const).map((color, index) => ({
            key: String(index),
            label: String(index),
            color,
        }))
        const { container } = render(<IssueTagsButton tags={tags} onTagClick={jest.fn()} surface="issues_list" />)

        expect(Array.from(container.querySelectorAll('[class*="IssueTagDot--"]'), (dot) => dot.className)).toEqual([
            expect.stringContaining('IssueTagDot--blue'),
            expect.stringContaining('IssueTagDot--teal'),
            expect.stringContaining('IssueTagDot--red'),
        ])
    })

    it('sends the key of the tag clicked in the list, then closes the list', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        const user = userEvent.setup()
        const onTagClick = jest.fn()
        render(<IssueTagsButton tags={TAGS} onTagClick={onTagClick} surface="issue_page" />)

        await user.click(screen.getByText('2 tags'))
        await user.click(await screen.findByLabelText('Show issues tagged Cause in trace'))

        expect(onTagClick).toHaveBeenCalledWith('cause_in_trace')
        await waitFor(() => expect(screen.queryByLabelText('Issue tags')).not.toBeInTheDocument())
        expect(capture.mock.calls).toEqual([
            ['error_tracking_issue_tags_opened', { ui_source: 'issue_page', tag_count: 2 }],
            ['error_tracking_issue_tag_clicked', { ui_source: 'issue_page' }],
        ])
        capture.mockRestore()
    })

    it('reports opening the list, not closing it', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        const user = userEvent.setup()
        render(<IssueTagsButton tags={TAGS} onTagClick={jest.fn()} surface="issues_list" />)

        await user.click(screen.getByText('2 tags'))
        await screen.findByLabelText('Issue tags')
        await user.keyboard('{Escape}')

        await waitFor(() => expect(screen.queryByLabelText('Issue tags')).not.toBeInTheDocument())
        expect(capture.mock.calls).toEqual([
            ['error_tracking_issue_tags_opened', { ui_source: 'issues_list', tag_count: 2 }],
        ])
        capture.mockRestore()
    })

    it('links to the tag rules settings without filtering by a tag', async () => {
        const user = userEvent.setup()
        const onTagClick = jest.fn()
        render(<IssueTagsButton tags={TAGS} onTagClick={onTagClick} surface="issue_page" />)

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
