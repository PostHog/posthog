import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { newSpaceLogic } from './newSpaceLogic'

describe('newSpaceLogic', () => {
    let createBody: Record<string, unknown> | null = null
    let starBody: Record<string, unknown> | null = null
    let createStatus = 201
    let createdStarred = true

    beforeEach(() => {
        createBody = null
        starBody = null
        createStatus = 201
        createdStarred = true
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [{ id: 'space-billing', name: 'billing', system_role: null }],
            },
            post: {
                '/api/projects/:team_id/task_channels/': async ({ request }) => {
                    createBody = (await request.json()) as Record<string, unknown>
                    return createStatus === 201
                        ? [201, { id: 'space-new', name: createBody.name, starred: createdStarred }]
                        : [createStatus, { detail: 'Something went wrong' }]
                },
                '/api/projects/:team_id/task_channels/:id/star/': async ({ request }) => {
                    starBody = (await request.json()) as Record<string, unknown>
                    return [204]
                },
            },
        })
        initKeaTests()
    })

    it.each([
        ['stars on create', true, null],
        ['stars through the star endpoint when create returns it unstarred', false, { starred: true }],
    ])('creates a public space, %s, and opens it', async (_, starred, expectedStarBody) => {
        createdStarred = starred
        const logic = newSpaceLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openNewSpace()
        logic.actions.setName('Mobile App ')
        logic.actions.submitNewSpace()
        await expectLogic(logic).toDispatchActions(['createSpaceSuccess']).toFinishAllListeners()

        expect(createBody).toEqual({ name: 'mobile-app', channel_type: 'public', star: true })
        expect(starBody).toEqual(expectedStarBody)
        expect(logic.values).toMatchObject({ isOpen: false, submitting: false })
        expect(router.values.location.pathname).toContain(urls.taskSpace('space-new'))
    })

    it('keeps the dialog open and usable when the create fails', async () => {
        createStatus = 500
        const logic = newSpaceLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openNewSpace()
        logic.actions.setName('mobile')
        logic.actions.submitNewSpace()
        await expectLogic(logic).toDispatchActions(['createSpaceFailure']).toFinishAllListeners()

        expect(logic.values).toMatchObject({ isOpen: true, submitting: false, name: 'mobile' })
    })

    it.each([
        ['', 'Enter a name for the space.'],
        ['Billing', '#billing already exists. Try another name.'],
        ['general', '"general" is reserved for your team\'s shared space.'],
    ])('does not create a space named %p', async (name, error) => {
        const logic = newSpaceLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.openNewSpace()
        logic.actions.setName(name)
        logic.actions.submitNewSpace()
        await expectLogic(logic).toFinishAllListeners()

        expect(createBody).toBeNull()
        expect(logic.values).toMatchObject({ isOpen: true, nameError: error })
    })
})
