import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiRequest } from 'lib/api'

import { initKeaTests } from '~/test/init'

import * as messagingApi from 'products/messaging/frontend/generated/api'
import type { MessageCategoryApi } from 'products/messaging/frontend/generated/api.schemas'

import { customerIOImportLogic } from './customerIOImportLogic'
import { newCategoryLogic } from './newCategoryLogic'
import { optOutCategoriesLogic } from './optOutCategoriesLogic'
import { optOutSceneLogic } from './optOutSceneLogic'

const NEWSLETTER: MessageCategoryApi = {
    id: 'topic-1',
    key: 'newsletter',
    name: 'Newsletter',
    description: '',
    public_description: '',
    category_type: 'marketing',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    created_by: null,
    deleted: false,
}

async function submitTopicForm(category?: MessageCategoryApi): Promise<void> {
    const logic = newCategoryLogic({ category })
    logic.mount()
    logic.actions.setCategoryFormValues({ name: 'Newsletter', key: 'newsletter' })
    await expectLogic(logic, () => logic.actions.submitCategoryForm()).toDispatchActions(['submitCategoryFormSuccess'])
}

async function deleteTopic(): Promise<void> {
    await expectLogic(optOutCategoriesLogic, () =>
        optOutCategoriesLogic.actions.deleteCategory(NEWSLETTER.id)
    ).toFinishAllListeners()
}

async function openPreferencesPage(popup: 'opened' | 'blocked'): Promise<void> {
    jest.spyOn(messagingApi, 'messagingPreferencesGenerateLinkCreate').mockResolvedValue({
        preferences_url: 'https://example.com/preferences/abc',
    })
    jest.spyOn(window, 'open').mockReturnValue(popup === 'opened' ? window : null)
    optOutSceneLogic.mount()
    await expectLogic(optOutSceneLogic, () =>
        optOutSceneLogic.actions.openPreferencesPage('jamie@example.com')
    ).toDispatchActions(['openPreferencesPageSuccess'])
}

async function importFromCustomerIOApi(): Promise<void> {
    jest.spyOn(ApiRequest.prototype, 'create').mockResolvedValue({
        status: 'completed',
        topics_found: 2,
        errors: [],
    })
    customerIOImportLogic.mount()
    await expectLogic(customerIOImportLogic, () => customerIOImportLogic.actions.rerunImport()).toFinishAllListeners()
}

async function importFromCustomerIOCsv(): Promise<void> {
    jest.spyOn(global, 'fetch').mockResolvedValue({
        ok: true,
        json: async () => ({ status: 'completed' }),
    } as Response)
    customerIOImportLogic.mount()
    customerIOImportLogic.actions.setCSVFile(new File(['email\n'], 'preferences.csv'))
    await expectLogic(customerIOImportLogic, () => customerIOImportLogic.actions.uploadCSV()).toFinishAllListeners()
}

function messagingEvents(): unknown[][] {
    return jest
        .mocked(posthog.capture)
        .mock.calls.filter(([event]) => typeof event === 'string' && event.startsWith('messaging '))
}

describe('topics tab usage tracking', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(posthog, 'capture')
        jest.spyOn(messagingApi, 'messagingCategoriesList').mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [NEWSLETTER],
        })
        jest.spyOn(messagingApi, 'messagingCategoriesCreate').mockResolvedValue(NEWSLETTER)
        jest.spyOn(messagingApi, 'messagingCategoriesPartialUpdate').mockResolvedValue(NEWSLETTER)
        jest.spyOn(ApiRequest.prototype, 'get').mockResolvedValue({})
        optOutCategoriesLogic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        { action: 'creating a topic', act: () => submitTopicForm(), expected: [['messaging topic created']] },
        {
            action: 'editing a topic',
            act: () => submitTopicForm(NEWSLETTER),
            expected: [['messaging topic updated']],
        },
        { action: 'deleting a topic', act: deleteTopic, expected: [['messaging topic deleted']] },
        {
            action: 'opening the preferences page',
            act: () => openPreferencesPage('opened'),
            expected: [['messaging preferences page opened']],
        },
        { action: 'a blocked preferences page popup', act: () => openPreferencesPage('blocked'), expected: [] },
        {
            action: 'a Customer.io API import',
            act: importFromCustomerIOApi,
            expected: [['messaging customer.io import completed', { source: 'api' }]],
        },
        {
            action: 'a Customer.io CSV import',
            act: importFromCustomerIOCsv,
            expected: [['messaging customer.io import completed', { source: 'csv' }]],
        },
    ])('after $action, captures $expected', async ({ act, expected }) => {
        await act()

        expect(messagingEvents()).toEqual(expected)
    })
})
