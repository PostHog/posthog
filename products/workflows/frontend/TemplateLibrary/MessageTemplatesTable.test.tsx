import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { MessageTemplatesTable } from './MessageTemplatesTable'
import type { MessageTemplate } from './types'

const TEMPLATE = { id: 'tmpl-1', name: 'Order receipt', description: '', tags: [] } as unknown as MessageTemplate

describe('MessageTemplatesTable', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': { results: [TEMPLATE] },
                '/api/projects/:team_id/tags': [],
            },
        })
    })

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    it.each([
        [AccessControlLevel.Viewer, 'true'],
        [AccessControlLevel.Editor, 'false'],
    ])('gives a workflows %s card actions with aria-disabled=%s', async (workflowAccess, expectedDisabled) => {
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
                <MessageTemplatesTable />
            </Provider>
        )

        const card = await screen.findByText('Order receipt')
        fireEvent.click(within(card.closest('[data-attr="message-template-item"]')!).getByLabelText('more'))

        await waitFor(() => expect(screen.getByText('Edit tags')).toBeInTheDocument())
        const menuItems = ['Duplicate', 'Edit tags', 'Delete'].map((label) =>
            screen.getByText(label).closest('[role="menuitem"]')
        )
        for (const item of menuItems) {
            expect(item).toHaveAttribute('aria-disabled', expectedDisabled)
        }
    })
})
