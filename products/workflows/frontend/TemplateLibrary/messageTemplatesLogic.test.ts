import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import type { MessageTemplateListApi } from 'products/messaging/frontend/generated/api.schemas'

import { messageTemplatesLogic } from './messageTemplatesLogic'
import type { MessageTemplate } from './types'

describe('messageTemplatesLogic', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('duplicates the editable design when the list response omits it', async () => {
        const listTemplate = {
            id: 'template-id',
            name: 'Welcome',
            description: 'Welcome email',
            content: { templating: 'liquid', email: { subject: 'Hello', html: '<p>Hello</p>' } },
        } as MessageTemplateListApi
        const listContent = listTemplate.content ?? {}
        const listEmail = listContent.email ?? {}
        const fullTemplate = {
            ...listTemplate,
            content: {
                ...listContent,
                email: { ...listEmail, design: { body: { rows: [] } } },
            },
        } as MessageTemplate
        jest.spyOn(api.messaging, 'getTemplates').mockResolvedValue({ results: [listTemplate], count: 1 } as Awaited<
            ReturnType<typeof api.messaging.getTemplates>
        >)
        jest.spyOn(api.messaging, 'getTemplate').mockResolvedValue(fullTemplate)
        const createTemplate = jest.spyOn(api.messaging, 'createTemplate').mockResolvedValue({
            ...fullTemplate,
            id: 'copy-id',
        })

        initKeaTests()
        const logic = messageTemplatesLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.duplicateTemplate(listTemplate)).toDispatchActions([
            'duplicateTemplateSuccess',
        ])
        expect(createTemplate).toHaveBeenCalledWith(
            expect.objectContaining({ name: 'Welcome (copy)', content: fullTemplate.content })
        )

        logic.unmount()
    })
})
