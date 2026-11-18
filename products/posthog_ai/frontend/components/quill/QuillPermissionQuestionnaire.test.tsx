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

const WITH_REQUIRED_NOTE: ApprovalCardOption[] = [
    ...OPTIONS,
    {
        optionId: 'redirect',
        label: 'Do it differently',
        decision: 'declined',
        primary: false,
        remembered: false,
        requiresFeedback: true,
        supportsFeedback: false,
    },
]

describe('QuillPermissionQuestionnaire', () => {
    afterEach(() => {
        cleanup()
    })

    test.each([
        {
            answer: 'the approve choice',
            options: OPTIONS,
            pick: () => fireEvent.click(screen.getByText('Yes')),
            expected: ['allow'],
        },
        {
            answer: 'the plain decline',
            options: OPTIONS,
            pick: () => fireEvent.click(screen.getByText('No')),
            expected: ['reject'],
        },
        {
            answer: 'a typed note',
            options: OPTIONS,
            pick: () =>
                fireEvent.change(screen.getByLabelText('Tell the agent what to do differently'), {
                    target: { value: 'use the staging project' },
                }),
            expected: ['reject', 'use the staging project'],
        },
        {
            answer: 'a note under its own decline when several take one',
            options: WITH_REQUIRED_NOTE,
            pick: () =>
                fireEvent.change(screen.getByLabelText('Do it differently'), {
                    target: { value: 'use the staging project' },
                }),
            expected: ['redirect', 'use the staging project'],
        },
    ])('sends $answer on submit', ({ options, pick, expected }) => {
        const onRespond = jest.fn()
        render(
            <QuillPermissionQuestionnaire
                headline="Update the task summary"
                evidence={null}
                options={options}
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
