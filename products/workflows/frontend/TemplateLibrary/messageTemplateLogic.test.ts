import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { ResourceEditedEvent } from '~/types'

import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

import { messageTemplateLogic } from './messageTemplateLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const mockToast = require('lib/lemon-ui/LemonToast').lemonToast

describe('messageTemplateLogic', () => {
    let logic: ReturnType<typeof messageTemplateLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/:id/': { id: 'existing-id', name: 'Existing' },
                '/api/environments/:team_id/hog_functions/:id/': { id: 'message-id', name: 'Sent message' },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('unsaved-changes guard', () => {
        let confirmSpy: jest.SpyInstance

        beforeEach(() => {
            // window.confirm is the boundary kea-router calls to block in-app navigation.
            confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true)
            logic = messageTemplateLogic({ id: 'new' })
            logic.mount()
        })

        afterEach(() => {
            confirmSpy.mockRestore()
        })

        it.each([
            { description: 'blocks navigation away from an unsaved new template', changed: true, expectedCalls: 1 },
            {
                description: 'does not block navigation when there are no unsaved changes',
                changed: false,
                expectedCalls: 0,
            },
        ])('$description', async ({ changed, expectedCalls }) => {
            if (changed) {
                logic.actions.setTemplateValue('name', 'My one-hour template')
                await expectLogic(logic).toMatchValues({ templateChanged: true })
            } else {
                await expectLogic(logic).toMatchValues({ templateChanged: false })
            }

            router.actions.push('/workflows/library')

            expect(confirmSpy).toHaveBeenCalledTimes(expectedCalls)
        })
    })

    describe('submit validation feedback', () => {
        beforeEach(() => {
            jest.clearAllMocks()
        })

        it.each([
            {
                missing: 'name',
                prefill: { key: 'content.email.subject', value: 'Welcome' },
                toast: 'Name is required',
            },
            {
                missing: 'subject',
                prefill: { key: 'name', value: 'Welcome email' },
                toast: 'Subject is required',
            },
        ])('toasts when the $missing is missing', async ({ prefill, toast }) => {
            logic = messageTemplateLogic({ id: 'new' })
            logic.mount()

            logic.actions.setTemplateValue(prefill.key, prefill.value)
            await expectLogic(logic, () => {
                logic.actions.submitTemplate()
            }).toDispatchActions(['submitTemplateFailure'])

            expect(mockToast.error).toHaveBeenCalledWith(toast)
        })
    })

    describe('save failure feedback', () => {
        beforeEach(() => {
            jest.clearAllMocks()
        })

        it.each([
            {
                description: '404 tells the user the template is gone from this environment',
                status: 404,
                toast: 'This template no longer exists in this environment. It may have been deleted.',
                withButton: true,
            },
            {
                description: 'other failures fall back to a generic retry message',
                status: 500,
                toast: 'Failed to save template. Please try again.',
                withButton: false,
            },
        ])('$description', async ({ status, toast, withButton }) => {
            useMocks({
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': () => [status, { detail: 'nope' }],
                },
            })

            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.saveTemplate({ id: 'existing-id', name: 'Existing' })
            }).toDispatchActions(['saveTemplateFailure'])

            if (withButton) {
                expect(mockToast.error).toHaveBeenCalledWith(
                    toast,
                    expect.objectContaining({ button: expect.anything() })
                )
            } else {
                expect(mockToast.error).toHaveBeenCalledWith(toast)
            }
        })
    })

    describe('edited elsewhere', () => {
        const LOADED_AT = '2026-01-01T00:00:00Z'
        const LATER = '2026-01-01T00:01:00Z'
        let serverTemplate: { id: string; name: string; updated_at: string }

        const edited = (overrides: Partial<ResourceEditedEvent> = {}): ResourceEditedEvent => ({
            notification_type: 'resource_edited',
            team_id: 1,
            resource_type: 'MessageTemplate',
            resource_id: 'existing-id',
            updated_at: LATER,
            actor_user_id: null,
            ...overrides,
        })

        beforeEach(async () => {
            serverTemplate = { id: 'existing-id', name: 'Existing', updated_at: LOADED_AT }
            useMocks({
                get: {
                    '/api/environments/:team_id/messaging_templates/:id/': () => [200, serverTemplate],
                },
                patch: {
                    '/api/environments/:team_id/messaging_templates/:id/': () => [
                        200,
                        { ...serverTemplate, name: 'Saved here', updated_at: LATER },
                    ],
                },
            })
            logic = messageTemplateLogic({ id: 'existing-id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
            // From here a reload shows as this name on the form.
            serverTemplate = { ...serverTemplate, name: 'Renamed by the agent', updated_at: LATER }
        })

        // A clean form takes the server copy at once. Unsaved edits get the banner instead of a silent replacement.
        it.each([
            { description: 'reloads a clean form', dirty: false, reloads: true },
            { description: 'warns instead of replacing unsaved edits', dirty: true, reloads: false },
        ])('$description', async ({ dirty, reloads }) => {
            if (dirty) {
                logic.actions.setTemplateValue('name', 'My edit')
            }

            await expectLogic(logic, () => {
                resourceEditedLogic.actions.resourceEdited(edited())
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                externallyEdited: !reloads,
                isSyncingExternalEdit: false,
                templateChanged: dirty,
            })
            expect(logic.values.template.name).toBe(reloads ? 'Renamed by the agent' : 'My edit')
        })

        it.each([
            { description: 'its own save echo', event: edited({ updated_at: LOADED_AT }) },
            { description: 'another template', event: edited({ resource_id: 'other-id' }) },
            { description: 'another resource type', event: edited({ resource_type: 'HogFlow' }) },
        ])('ignores $description', async ({ event }) => {
            await expectLogic(logic, () => {
                resourceEditedLogic.actions.resourceEdited(event)
            }).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ externallyEdited: false, isSyncingExternalEdit: false })
            expect(logic.values.template.name).toBe('Existing')
        })

        // The realtime echo of our own save can beat its HTTP response, while the loaded stamp is still the old one.
        it('parks an event that arrives during a save and drops the echo once the save lands', async () => {
            await expectLogic(logic, () => {
                logic.actions.saveTemplate({ ...logic.values.template, name: 'Saved here' })
                resourceEditedLogic.actions.resourceEdited(edited())
            })
                .toDispatchActions(['setDeferredExternalEdit', 'saveTemplateSuccess', 'replayDeferredExternalEdit'])
                .toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ externallyEdited: false, deferredExternalEdit: null })
            expect(logic.values.template.name).toBe('Saved here')
        })

        // A failed reload leaves the stale copy on the form, so the conflict must stay visible with its retry.
        it('shows the banner when the reload of a clean form fails', async () => {
            useMocks({
                get: { '/api/environments/:team_id/messaging_templates/:id/': () => [500, { detail: 'nope' }] },
            })

            await expectLogic(logic, () => {
                resourceEditedLogic.actions.resourceEdited(edited())
            })
                .toDispatchActions(['loadTemplateFailure'])
                .toFinishAllListeners()

            await expectLogic(logic).toMatchValues({ externallyEdited: true, isSyncingExternalEdit: false })
            expect(logic.values.template.name).toBe('Existing')
        })

        it('reload from the banner replaces the unsaved edits with the server copy', async () => {
            logic.actions.setTemplateValue('name', 'My edit')
            await expectLogic(logic, () => {
                resourceEditedLogic.actions.resourceEdited(edited())
            }).toMatchValues({ externallyEdited: true })

            await expectLogic(logic, () => {
                logic.actions.syncExternalEdit()
            })
                .toDispatchActions(['loadTemplateSuccess'])
                .toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                externallyEdited: false,
                isSyncingExternalEdit: false,
                templateChanged: false,
            })
            expect(logic.values.template.name).toBe('Renamed by the agent')
        })
    })

    describe('starting-point picker', () => {
        it.each([
            {
                description: 'opens for a brand-new template',
                props: { id: 'new' },
                expectedOpen: true,
            },
            {
                description: 'does not open when creating from a sent message',
                props: { id: 'new', messageId: 'message-id' },
                expectedOpen: false,
            },
            {
                description: 'does not open for an existing template',
                props: { id: 'existing-id' },
                expectedOpen: false,
            },
        ])('$description', async ({ props, expectedOpen }) => {
            logic = messageTemplateLogic(props)
            logic.mount()

            await expectLogic(logic).toMatchValues({ templatePickerOpen: expectedOpen })
        })
    })
})
