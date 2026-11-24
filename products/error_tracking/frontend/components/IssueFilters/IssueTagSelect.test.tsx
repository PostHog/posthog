import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import type { IssueTagState, IssueTagsFilter } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { IssueTagSelect } from './IssueTagSelect'

const DEFINITIONS = [{ key: 'cause_in_trace', label: 'Cause in trace', description: 'The cause is in the trace.' }]
const TWO_DEFINITIONS = [
    ...DEFINITIONS,
    { key: 'third_party', label: 'Third party', description: 'The error comes from third-party code.' },
]

function tagSelect(
    issueTags: IssueTagsFilter | null,
    onTagStateChange: (key: string, state: IssueTagState | null) => void = jest.fn(),
    definitions = DEFINITIONS
): JSX.Element {
    return (
        <IssueTagSelect
            definitions={definitions}
            loading={false}
            issueTags={issueTags}
            onTagStateChange={onTagStateChange}
            onClear={jest.fn()}
        />
    )
}

describe('IssueTagSelect', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('sets a tag from its checkbox and its has or has not buttons, keeping keyboard focus on the control', async () => {
        const user = userEvent.setup()
        const onTagStateChange = jest.fn()
        const { rerender } = render(tagSelect(null, onTagStateChange))
        await user.click(screen.getByLabelText('Tag filter: Any tag'))
        const checkbox = await screen.findByRole('checkbox')
        const hasNotButton = screen.getByText('Has not').closest('button') as HTMLElement

        await user.click(hasNotButton)
        expect(onTagStateChange).toHaveBeenLastCalledWith('cause_in_trace', 'hasNot')
        rerender(tagSelect({ has: [], hasNot: ['cause_in_trace'] }, onTagStateChange))
        expect(checkbox).toHaveAttribute('aria-checked', 'true')
        expect(hasNotButton).toHaveFocus()

        await user.click(hasNotButton)
        expect(onTagStateChange).toHaveBeenLastCalledWith('cause_in_trace', null)
        rerender(tagSelect(null, onTagStateChange))

        await user.click(checkbox)
        expect(onTagStateChange).toHaveBeenLastCalledWith('cause_in_trace', 'has')
        rerender(tagSelect({ has: ['cause_in_trace'], hasNot: [] }, onTagStateChange))
        expect(checkbox).toHaveFocus()

        await user.click(checkbox)
        expect(onTagStateChange).toHaveBeenLastCalledWith('cause_in_trace', null)
    })

    it.each([
        { from: 'no tag', issueTags: null, control: 'Has', sent: 'has' },
        { from: 'has not', issueTags: { has: [], hasNot: ['cause_in_trace'] }, control: 'Has', sent: 'has' },
        { from: 'has not', issueTags: { has: [], hasNot: ['cause_in_trace'] }, control: 'checkbox', sent: null },
    ])('from $from, pressing $control sets the tag to $sent', async ({ issueTags, control, sent }) => {
        const user = userEvent.setup()
        const onTagStateChange = jest.fn()
        render(tagSelect(issueTags, onTagStateChange))
        await user.click(screen.getByLabelText(/^Tag filter:/))

        await user.click(
            control === 'checkbox' ? await screen.findByRole('checkbox') : await screen.findByText(control)
        )

        expect(onTagStateChange).toHaveBeenLastCalledWith('cause_in_trace', sent)
    })

    it('lists the tags selected when it opens first, under their own heading', async () => {
        const user = userEvent.setup()
        render(tagSelect({ has: [], hasNot: ['third_party'] }, jest.fn(), TWO_DEFINITIONS))
        await user.click(screen.getByLabelText(/^Tag filter:/))

        const list = await screen.findAllByText(/^(Selected tags|Other tags|Cause in trace|Third party)$/)

        expect(list.map((element) => element.textContent)).toEqual([
            'Selected tags',
            'Third party',
            'Other tags',
            'Cause in trace',
        ])
    })

    it.each([
        {
            issueTags: { has: ['cause_in_trace'], hasNot: [] },
            text: 'Tags: Cause in trace',
            name: 'Tag filter: Tags: Cause in trace',
        },
        {
            issueTags: { has: [], hasNot: ['cause_in_trace'] },
            text: 'Tags: not Cause in trace',
            name: 'Tag filter: Tags: not Cause in trace',
        },
        {
            issueTags: { has: ['cause_in_trace'], hasNot: ['third_party'] },
            text: '2 tags',
            name: 'Tag filter: 2 tags, has Cause in trace, not Third party',
        },
    ])('shows "$text" on the button for its filter', ({ issueTags, text, name }) => {
        render(tagSelect(issueTags, jest.fn(), TWO_DEFINITIONS))

        expect(screen.getByLabelText(name)).toHaveTextContent(text)
    })
})
