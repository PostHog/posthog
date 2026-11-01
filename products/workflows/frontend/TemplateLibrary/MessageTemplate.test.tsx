import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { MessageTemplate } from './MessageTemplate'

const TEMPLATE_ID = 'tmpl-1'

describe('MessageTemplate', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/:id/': {
                    id: TEMPLATE_ID,
                    name: 'Order receipt',
                    description: '',
                    tags: [],
                    content: { email: { subject: 'Hi', html: '<p>Hi</p>', text: 'Hi', design: {} } },
                },
            },
        })
    })

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    it.each([
        [AccessControlLevel.Viewer, 'false', 'true'],
        [AccessControlLevel.Editor, 'true', 'false'],
    ])(
        'gives a workflows %s an editable title=%s and a disabled delete=%s',
        async (workflowAccess, expectedEditable, expectedDeleteDisabled) => {
            window.POSTHOG_APP_CONTEXT = {
                ...priorAppContext,
                resource_access_control: {
                    ...priorAppContext?.resource_access_control,
                    [AccessControlResourceType.Workflow]: workflowAccess,
                },
            } as AppContext
            initKeaTests()

            render(
                <Provider>
                    <MessageTemplate id={TEMPLATE_ID} />
                </Provider>
            )

            await waitFor(() =>
                expect(document.querySelector('.scene-title-section')).toHaveTextContent('Order receipt')
            )
            expect(document.querySelector('.scene-title-section')).toHaveAttribute('data-editable', expectedEditable)

            fireEvent.click(screen.getByLabelText('more'))
            await waitFor(() =>
                expect(document.querySelector('[data-attr="delete-message-template"]')).toBeInTheDocument()
            )
            expect(document.querySelector('[data-attr="delete-message-template"]')).toHaveAttribute(
                'aria-disabled',
                expectedDeleteDisabled
            )
        }
    )
})
