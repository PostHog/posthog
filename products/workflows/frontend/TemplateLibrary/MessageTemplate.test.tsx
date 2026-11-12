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

const ORDER_RECEIPT = {
    id: TEMPLATE_ID,
    name: 'Order receipt',
    description: '',
    tags: [],
    content: { email: { subject: 'Hi', html: '<p>Hi</p>', text: 'Hi', design: {} } },
}

const PASSWORD_RESET_WITH_DRAFT = {
    ...ORDER_RECEIPT,
    name: 'Password reset',
    transactional_hog_flow_id: 'flow-1',
    sensitive: false,
    draft_content: { email: { subject: 'Reset it', html: '<p>Reset</p>', text: 'Reset', design: {} } },
}

describe('MessageTemplate', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    const renderAs = async (workflowAccess: AccessControlLevel, templateName: string): Promise<void> => {
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

        await waitFor(() => expect(screen.getByText(templateName)).toBeInTheDocument())
    }

    it.each([
        [AccessControlLevel.Viewer, false, 'true'],
        [AccessControlLevel.Editor, true, 'false'],
    ])(
        'lets a workflows %s rename the template=%s and gives it disabled write actions=%s',
        async (workflowAccess, canRename, expectedWriteDisabled) => {
            useMocks({ get: { '/api/environments/:team_id/messaging_templates/:id/': ORDER_RECEIPT } })
            await renderAs(workflowAccess, ORDER_RECEIPT.name)

            fireEvent.click(screen.getByText('Order receipt'))
            expect(!!screen.queryByPlaceholderText('Enter name')).toBe(canRename)

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

    it.each([
        [AccessControlLevel.Viewer, true],
        [AccessControlLevel.Editor, false],
    ])(
        'blocks a workflows %s from publishing, discarding or marking a transactional draft sensitive: %s',
        async (workflowAccess, writeDisabled) => {
            useMocks({ get: { '/api/environments/:team_id/messaging_templates/:id/': PASSWORD_RESET_WITH_DRAFT } })
            await renderAs(workflowAccess, PASSWORD_RESET_WITH_DRAFT.name)

            expect(screen.getByText('Publish').closest('button')).toHaveAttribute(
                'aria-disabled',
                String(writeDisabled)
            )

            fireEvent.click(screen.getByLabelText('More draft actions'))
            await waitFor(() =>
                expect(document.querySelector('[data-attr="message-template-discard-draft"]')).toBeInTheDocument()
            )
            expect(document.querySelector('[data-attr="message-template-discard-draft"]')).toHaveAttribute(
                'aria-disabled',
                String(writeDisabled)
            )

            fireEvent.click(screen.getByText('API'))
            await waitFor(() => expect(screen.getByLabelText('Protect sensitive data')).toBeInTheDocument())
            expect(screen.getByLabelText('Protect sensitive data').hasAttribute('disabled')).toBe(writeDisabled)
        }
    )
})
