import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { ApprovalCardOption } from '../../policy/permissionUtils'
import { QuillPermissionQuestionnaire } from './QuillPermissionQuestionnaire'

const OPTIONS: ApprovalCardOption[] = [
    {
        optionId: 'allow',
        label: 'Yes',
        decision: 'approved',
        primary: true,
        remembered: false,
        requiresFeedback: false,
        supportsFeedback: false,
    },
    {
        optionId: 'reject',
        label: 'No, and tell the agent what to do differently',
        decision: 'declined',
        primary: false,
        remembered: false,
        requiresFeedback: false,
        supportsFeedback: true,
    },
]

describe('QuillPermissionQuestionnaire', () => {
    afterEach(() => {
        cleanup()
    })

    test.each([
        { answer: 'the approve choice', pick: () => fireEvent.click(screen.getByText('Yes')), expected: ['allow'] },
        { answer: 'the plain decline', pick: () => fireEvent.click(screen.getByText('No')), expected: ['reject'] },
        {
            answer: 'a typed note',
            pick: () =>
                fireEvent.change(screen.getByLabelText('Tell the agent what to do differently'), {
                    target: { value: 'use the staging project' },
                }),
            expected: ['reject', 'use the staging project'],
        },
    ])('sends $answer on submit', ({ pick, expected }) => {
        const onRespond = jest.fn()
        render(
            <QuillPermissionQuestionnaire
                headline="Update the task summary"
                evidence={null}
                options={OPTIONS}
                responding={false}
                onRespond={onRespond}
            />
        )

        expect(screen.getByText('Send').closest('button')).toHaveAttribute('aria-disabled', 'true')
        pick()
        fireEvent.click(screen.getByText('Send'))

        expect(onRespond).toHaveBeenCalledWith(...expected)
    })
})
