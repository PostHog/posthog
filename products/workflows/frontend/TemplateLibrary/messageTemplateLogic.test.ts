import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { NEW_TEMPLATE } from './constants'
import { messageTemplateLogic } from './messageTemplateLogic'

describe('messageTemplateLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team/messaging_templates': { count: 0, results: [] },
                '/api/environments/:team/messaging_templates/:id': NEW_TEMPLATE,
            },
            post: {
                '/api/environments/:team/messaging_templates': (req) => {
                    const body = req.body as Record<string, unknown>
                    return {
                        ...body,
                        id: 'created-template-id',
                        created_at: '2024-01-01T00:00:00Z',
                        updated_at: '2024-01-01T00:00:00Z',
                    }
                },
            },
        })
        initKeaTests()
    })

    describe('state reset on navigation to new template', () => {
        it('should reset form state when navigating to new template URL', async () => {
            const logic = messageTemplateLogic({ id: 'new' })
            logic.mount()

            // Modify the form values
            logic.actions.setTemplateValue('name', 'Modified Name')
            logic.actions.setTemplateValue('description', 'Modified Description')

            await expectLogic(logic).toMatchValues({
                template: expect.objectContaining({
                    name: 'Modified Name',
                    description: 'Modified Description',
                }),
            })

            // Navigate to the new template URL (simulates going to list and back to new)
            router.actions.push('/workflows/library/templates/new')

            await expectLogic(logic).toMatchValues({
                template: expect.objectContaining({
                    id: 'new',
                    name: '',
                    description: '',
                }),
            })
        })

        it('should reset template id to "new" after creating a template and navigating back', async () => {
            const logic = messageTemplateLogic({ id: 'new' })
            logic.mount()

            // Simulate what happens after saveTemplateSuccess - the template now has a real ID
            logic.actions.setTemplateValue('name', 'Created Template')
            logic.actions.resetTemplate({
                ...NEW_TEMPLATE,
                id: 'created-template-id',
                name: 'Created Template',
            })

            await expectLogic(logic).toMatchValues({
                template: expect.objectContaining({
                    id: 'created-template-id',
                    name: 'Created Template',
                }),
            })

            // Navigate to new template URL
            router.actions.push('/workflows/library/templates/new')

            // Should reset to NEW_TEMPLATE defaults, including id: 'new'
            await expectLogic(logic).toMatchValues({
                template: expect.objectContaining({
                    id: 'new',
                    name: '',
                }),
            })
        })
    })
})
