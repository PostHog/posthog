import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ResourceEditedEvent } from '~/types'

import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

import { messageTemplateLogic } from './messageTemplateLogic'
import { MessageTemplate } from './types'

const TEMPLATE_ID = 'template-external-1'
const LOADED_AT = '2026-05-01T00:00:00.000Z'
const NEWER = '2026-06-01T00:00:00.000Z'
const OLDER = '2026-04-01T00:00:00.000Z'

const makeTemplate = (overrides: Partial<MessageTemplate> = {}): MessageTemplate => ({
    id: TEMPLATE_ID,
    name: 'External edits test',
    description: '',
    content: {
        templating: 'liquid',
        email: {
            from: '',
            to: '',
            subject: 'Hello',
            html: '<p>Hello</p>',
            text: 'Hello',
            design: { body: { id: 'b', rows: [] } },
        } as MessageTemplate['content']['email'],
    },
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: LOADED_AT,
    created_by: null,
    ...overrides,
})

const makeEvent = (overrides: Partial<ResourceEditedEvent> = {}): ResourceEditedEvent => ({
    notification_type: 'resource_edited',
    team_id: 1,
    resource_type: 'MessageTemplate',
    resource_id: TEMPLATE_ID,
    updated_at: NEWER,
    actor_user_id: 99,
    ...overrides,
})

describe('messageTemplateLogic external edits', () => {
    let logic: ReturnType<typeof messageTemplateLogic.build>
    let getCalls: number

    beforeEach(async () => {
        getCalls = 0
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_templates/:id/': () => {
                    getCalls += 1
                    return [200, makeTemplate()]
                },
            },
        })
        initKeaTests()
        resourceEditedLogic.mount()
        logic = messageTemplateLogic({ id: TEMPLATE_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])
        // The initial load counts as one GET; assertions below track edits beyond it.
        expect(getCalls).toBe(1)
    })

    afterEach(() => {
        logic.unmount()
    })

    it('silently reconciles (sync + reload) when the local state is clean', async () => {
        await expectLogic(logic, () => {
            resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
        }).toDispatchActions(['setSyncingExternalEdit', 'loadTemplate', 'loadTemplateSuccess'])

        // Reloaded from the server, no banner, syncing overlay cleared, form left clean.
        expect(getCalls).toBe(2)
        expect(logic.values.externallyEdited).toBe(false)
        expect(logic.values.isSyncingExternalEdit).toBe(false)
        expect(logic.values.templateChanged).toBe(false)
    })

    it('warns instead of clobbering when there are unsaved local edits', async () => {
        logic.actions.setTemplateValue('name', 'My local edit')
        await expectLogic(logic).toMatchValues({ templateChanged: true })

        await expectLogic(logic, () => {
            resourceEditedLogic.actions.resourceEdited(makeEvent({ updated_at: NEWER }))
        }).toDispatchActions(['setExternallyEdited'])

        // Banner shown, no destructive reload, no syncing overlay.
        expect(logic.values.externallyEdited).toBe(true)
        expect(logic.values.isSyncingExternalEdit).toBe(false)
        expect(getCalls).toBe(1)
    })

    it.each([
        ['equal updated_at (our own save echo)', { updated_at: LOADED_AT }],
        ['older updated_at', { updated_at: OLDER }],
        ['a different template', { resource_id: 'some-other-template' }],
        ['a different resource type', { resource_type: 'HogFlow' }],
    ])('ignores %s', async (_label, overrides) => {
        resourceEditedLogic.actions.resourceEdited(makeEvent(overrides))
        await expectLogic(logic).toNotHaveDispatchedActions(['setSyncingExternalEdit', 'setExternallyEdited'])

        expect(getCalls).toBe(1)
        expect(logic.values.externallyEdited).toBe(false)
    })
})
