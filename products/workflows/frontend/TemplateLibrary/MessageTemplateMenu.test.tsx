import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplateMenu } from './MessageTemplateMenu'

const CODE_MANAGED = {
    id: 'existing-id',
    name: 'Welcome',
    content: { templating: 'liquid', email: { subject: 'Welcome', html: '<p>Hi</p>', text: 'Hi' } },
    key: 'welcome',
    managed_by: 'code',
    source_path: 'emails/welcome.html',
}

describe('MessageTemplateMenu', () => {
    let logic: ReturnType<typeof messageTemplateLogic.build>
    let patchBodies: Record<string, unknown>[]

    beforeEach(async () => {
        patchBodies = []
        useMocks({
            get: { '/api/environments/:team_id/messaging_templates/:id/': CODE_MANAGED },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id/': async ({ request }: { request: Request }) => {
                    patchBodies.push(await request.json())
                    return [200, { ...CODE_MANAGED, managed_by: 'gui' }]
                },
            },
        })
        initKeaTests()
        logic = messageTemplateLogic({ id: 'existing-id' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
        render(<MessageTemplateMenu id="existing-id" />)
        fireEvent.click(screen.getByLabelText('more'))
        fireEvent.click(await screen.findByText('Stop managing in code'))
        await screen.findByText('Stop managing this template in code?')
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('keeps the template managed by code when the release is cancelled', async () => {
        fireEvent.click(screen.getByText('Cancel'))

        await waitFor(() => expect(screen.queryByText('Stop managing this template in code?')).not.toBeInTheDocument())
        expect(patchBodies).toEqual([])
        expect(logic.values.isCodeManaged).toBe(true)
    })

    it('releases the template to PostHog once the release is confirmed', async () => {
        const dialog = screen.getByText('Stop managing this template in code?').closest('.LemonModal') as HTMLElement
        fireEvent.click(dialog.querySelector('[data-attr="message-template-release-confirm"]') as HTMLElement)

        await expectLogic(logic).toDispatchActions(['releaseTemplateSuccess'])
        expect(patchBodies).toEqual([{ managed_by: 'gui' }])
        expect(logic.values.isCodeManaged).toBe(false)
    })
})
