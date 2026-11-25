import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { HogFlowAction } from '../../../types'
import { CanvasPreviewPersonContext } from '../CanvasPreviewPersonContext'
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

    it('shows plain words once the render budget for a pass is spent', () => {
        let now = 50_000
        jest.spyOn(Date, 'now').mockImplementation(() => (now += 400))
        const liquidEmail = (id: string): HogFlowAction =>
            ({
                ...plainTextEmail,
                id,
                config: {
                    ...plainTextEmail.config,
                    inputs: { email: { ...(plainTextEmail.config as any).inputs.email, templating: 'liquid' } },
                },
            }) as HogFlowAction
        const person = { id: 'p', properties: { first_name: 'Sam' } }

        const { container } = render(
            <CanvasPreviewPersonContext.Provider value={person}>
                <EmailPreview email={emailContent(liquidEmail('first'))!} title="First" />
                <EmailPreview email={emailContent(liquidEmail('second'))!} title="Second" />
            </CanvasPreviewPersonContext.Provider>
        )

        const previews = Array.from(container.querySelectorAll('.line-clamp-6'), (node) => node.textContent)
        expect(previews).toEqual([expect.stringContaining('Hi Sam,'), expect.stringContaining('Hi first name,')])
        jest.restoreAllMocks()
    })
})
