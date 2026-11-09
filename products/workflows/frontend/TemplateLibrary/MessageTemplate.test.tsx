import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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
        'gives a workflows %s an editable title=%s and disabled write actions=%s',
        async (workflowAccess, expectedEditable, expectedWriteDisabled) => {
            window.POSTHOG_APP_CONTEXT = {
                ...priorAppContext,
                resource_access_control: {
                    ...priorAppContext?.resource_access_control,
                    [AccessControlResourceType.Workflow]: workflowAccess,
                },
            } as AppContext
            initKeaTests()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API], {
                [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API]: true,
            })

            render(
                <Provider>
                    <MessageTemplate id={TEMPLATE_ID} />
                </Provider>
            )

            await waitFor(() =>
                expect(document.querySelector('.scene-title-section')).toHaveTextContent('Order receipt')
            )
            expect(document.querySelector('.scene-title-section')).toHaveAttribute('data-editable', expectedEditable)
            expect(document.querySelector('[data-attr="send-test-message-template"]')).toHaveAttribute(
                'aria-disabled',
                expectedWriteDisabled
            )

            fireEvent.click(screen.getByLabelText('more'))
            await waitFor(() =>
                expect(document.querySelector('[data-attr="delete-message-template"]')).toBeInTheDocument()
            )
            expect(document.querySelector('[data-attr="delete-message-template"]')).toHaveAttribute(
                'aria-disabled',
                expectedWriteDisabled
            )

            fireEvent.click(screen.getByText('API'))
            await waitFor(() =>
                expect(document.querySelector('[data-attr="make-message-template-transactional"]')).toBeInTheDocument()
            )
            expect(document.querySelector('[data-attr="make-message-template-transactional"]')).toHaveAttribute(
                'aria-disabled',
                expectedWriteDisabled
            )
        }
    )
})
