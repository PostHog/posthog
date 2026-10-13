import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import * as messagingApi from 'products/messaging/frontend/generated/api'
import type {
    MessageTemplateApi,
    MessageTemplateApi as MessageTemplateListApi,
} from 'products/messaging/frontend/generated/api.schemas'

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
        jest.spyOn(messagingApi, 'messagingTemplatesList').mockResolvedValue({
            results: [listTemplate],
            count: 1,
        } as Awaited<ReturnType<typeof messagingApi.messagingTemplatesList>>)
        const retrieve = jest
            .spyOn(messagingApi, 'messagingTemplatesRetrieve')
            .mockResolvedValue(fullTemplate as MessageTemplateApi)
        const createTemplate = jest.spyOn(messagingApi, 'messagingTemplatesCreate').mockResolvedValue({
            ...listTemplate,
            id: 'copy-id',
            content: fullTemplate.content,
        } as MessageTemplateApi)

        initKeaTests()
        const logic = messageTemplatesLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadTemplatesSuccess'])
        await expectLogic(logic, () => logic.actions.duplicateTemplate(logic.values.templates[0])).toDispatchActions([
            'duplicateTemplateSuccess',
        ])
        expect(retrieve).toHaveBeenCalledWith(String(ApiConfig.getCurrentTeamId()), listTemplate.id)
        expect(createTemplate).toHaveBeenCalledWith(
            String(ApiConfig.getCurrentTeamId()),
            expect.objectContaining({ name: 'Welcome (copy)', content: fullTemplate.content })
        )

        logic.unmount()
    })
})
