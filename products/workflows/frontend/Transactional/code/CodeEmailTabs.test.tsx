import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { codeEmailLogic } from './codeEmailLogic'
import { CodeEmailTabs } from './CodeEmailTabs'

const codeEmail: CodeEmailApi = {
    id: 'email-id',
    key: 'password-reset',
    hog_flow_id: 'flow-id',
    description: '',
    tags: [],
    sensitive: true,
    source_url: null,
    source_origin: null,
    created_at: '2026-01-01T00:00:00Z',
    user_access_level: 'editor',
}

const BANNER = "This email's metrics and sends couldn't load. Check your connection and try again."

describe('CodeEmailTabs', () => {
    afterEach(cleanup)

    it('shows a retry on metrics and sends while the workflow fails to load, and the content once it loads', async () => {
        let workflowAnswers = 0
        useMocks({
            get: {
                '/api/projects/:team_id/transactional_code_emails/:id/': codeEmail,
                '/api/environments/:team_id/hog_flows/:id/': () =>
                    ++workflowAnswers === 1 ? [500, { detail: 'Unavailable' }] : [200, { id: 'flow-id', actions: [] }],
            },
        })
        initKeaTests()
        const logic = codeEmailLogic({ id: 'email-id' })
        logic.mount()
        render(
            <Provider>
                <BindLogic logic={codeEmailLogic} props={{ id: 'email-id' }}>
                    <CodeEmailTabs codeEmail={codeEmail} />
                </BindLogic>
            </Provider>
        )

        await screen.findByText(BANNER)
        fireEvent.click(screen.getByText('Sends'))
        expect(screen.getByText(BANNER)).toBeInTheDocument()
        fireEvent.click(screen.getByText('API'))
        expect(screen.queryByText(BANNER)).not.toBeInTheDocument()
        expect(document.querySelector('[data-attr=code-email-api-example]')).toHaveTextContent('password-reset')

        fireEvent.click(screen.getByText('Metrics'))
        await act(async () => {
            fireEvent.click(screen.getAllByText('Try again')[0])
        })

        await waitFor(() => expect(screen.queryByText(BANNER)).not.toBeInTheDocument())
        expect(workflowAnswers).toBe(2)
        logic.unmount()
    })
})
