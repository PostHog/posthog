import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    let createBodies: Record<string, unknown>[]

    const openReleaseDialog = async (): Promise<void> => {
        fireEvent.click(await screen.findByText('Stop managing in code'))
        await screen.findByText('Stop managing this template in code?')
    }

    beforeEach(async () => {
        patchBodies = []
        createBodies = []
        useMocks({
            get: { '/api/environments/:team_id/messaging_templates/:id/': CODE_MANAGED },
            patch: {
                '/api/environments/:team_id/messaging_templates/:id/': async ({ request }: { request: Request }) => {
                    patchBodies.push(await request.json())
                    return [200, { ...CODE_MANAGED, managed_by: 'gui' }]
                },
            },
            post: {
                '/api/environments/:team_id/messaging_templates/': async ({ request }: { request: Request }) => {
                    createBodies.push(await request.json())
                    return [201, { id: 'copy-id' }]
                },
            },
        })
        initKeaTests()
        logic = messageTemplateLogic({ id: 'existing-id' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
        render(<MessageTemplateMenu id="existing-id" />)
        fireEvent.click(screen.getByLabelText('more'))
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('keeps the template managed by code when the release is cancelled', async () => {
        await openReleaseDialog()
        fireEvent.click(screen.getByText('Cancel'))

        await waitFor(() => expect(screen.queryByText('Stop managing this template in code?')).not.toBeInTheDocument())
        expect(patchBodies).toEqual([])
        expect(logic.values.isCodeManaged).toBe(true)
    })

    it('releases the template to PostHog once the release is confirmed', async () => {
        await openReleaseDialog()
        const dialog = screen.getByText('Stop managing this template in code?').closest('.LemonModal') as HTMLElement
        fireEvent.click(dialog.querySelector('[data-attr="message-template-release-confirm"]') as HTMLElement)

        await expectLogic(logic).toDispatchActions(['releaseTemplateSuccess'])
        expect(patchBodies).toEqual([{ managed_by: 'gui' }])
        expect(logic.values.isCodeManaged).toBe(false)
    })

    it('points Duplicate to the refused edits instead of copying the server version', async () => {
        act(() => logic.actions.setRefusedEdits({ ...logic.values.template, name: 'Welcome, edited here' }))
        const duplicate = (await screen.findByText('Duplicate')).closest('button') as HTMLElement

        fireEvent.click(duplicate)
        await expectLogic(logic).toFinishAllListeners()

        expect(duplicate).toHaveAttribute('aria-disabled', 'true')
        expect(createBodies).toEqual([])
    })
})
