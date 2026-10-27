import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { HogFlowAction } from '../../../types'
import { emailContent } from '../stepValues'
import { EmailPreview } from './EmailPreview'

const plainTextEmail = {
    id: 'invite',
    type: 'function_email',
    name: 'Invite',
    description: '',
    config: {
        template_id: 'template-email',
        inputs: {
            email: {
                value: {
                    subject: 'Invite your team',
                    html: '',
                    text: 'Hi {{ person.properties.first_name }},\n\nYou can invite three people for free.',
                },
            },
        },
    },
} as unknown as HogFlowAction

describe('EmailPreview', () => {
    it('shows the text of an email that has no design', () => {
        render(<EmailPreview email={emailContent(plainTextEmail)!} title="Invite preview" />)

        expect(screen.getByText(/You can invite three people for free/)).toBeInTheDocument()
    })
})
