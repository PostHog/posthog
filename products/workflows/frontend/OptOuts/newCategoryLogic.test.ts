import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import * as messagingApi from 'products/messaging/frontend/generated/api'

import { newCategoryLogic } from './newCategoryLogic'
import type { MessageCategory } from './optOutCategoriesLogic'

const BILLING_RECEIPTS: MessageCategory = {
    id: '0199c1aa-0000-7000-8000-000000000003',
    key: 'billing-receipts',
    name: 'Billing receipts',
    description: '',
    public_description: '',
    category_type: 'transactional',
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-01T10:00:00Z',
    created_by: null,
}

// A form field dispatches its name as a path array, the way kea-forms' Field does.
function typeInto(logic: ReturnType<typeof newCategoryLogic.build>, field: 'name' | 'key', value: string): void {
    logic.actions.setCategoryFormValue([field], value)
}

function rejectCreateWith(error: Error): void {
    jest.spyOn(messagingApi, 'messagingCategoriesCreate').mockRejectedValue(error)
}

function apiFieldError(attr: string, detail: string): ApiError {
    return new ApiError(detail, 400, undefined, { type: 'validation_error', code: 'invalid_input', detail, attr })
}

async function submitAndFail(logic: ReturnType<typeof newCategoryLogic.build>): Promise<void> {
    await expectLogic(logic, () => logic.actions.submitCategoryForm()).toDispatchActions(['submitCategoryFormFailure'])
}

function setAudienceFlag(enabled: boolean): void {
    featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: enabled })
}

describe('newCategoryLogic', () => {
    beforeEach(() => {
        initKeaTests()
        setAudienceFlag(true)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('slugifies the name into the key of a new topic on every name edit', () => {
        const logic = newCategoryLogic({})
        logic.mount()

        typeInto(logic, 'name', 'Product')
        typeInto(logic, 'name', 'Product updates')

        expect(logic.values.categoryForm.key).toBe('product-updates')
    })

    it.each([
        {
            name: 'Monthly product announcements for engineering and design teams worldwide',
            key: 'monthly-product-announcements-for-engineering-and-design-teams-w',
        },
        { name: `${'a'.repeat(63)} digest`, key: 'a'.repeat(63) },
        { name: '🎉 Product launches', key: 'product-launches' },
    ])('fills a key of at most 64 characters with no hyphen at either end: $key', ({ name, key }) => {
        const logic = newCategoryLogic({})
        logic.mount()

        typeInto(logic, 'name', name)

        expect(logic.values.categoryForm.key).toBe(key)
    })

    it.each([
        { key: 'a'.repeat(64), error: undefined },
        { key: 'a'.repeat(65), error: 'Keys can be at most 64 characters' },
    ])('accepts a key of up to 64 characters ($key.length characters)', ({ key, error }) => {
        const logic = newCategoryLogic({})
        logic.mount()

        typeInto(logic, 'key', key)

        expect(logic.values.categoryFormValidationErrors.key).toBe(error)
    })

    it.each([
        { handTyped: ['news'], kept: 'news' },
        { handTyped: ['news', 'product-updates'], kept: 'product-updates' },
    ])('keeps the hand-typed key $kept when the name changes afterwards', ({ handTyped, kept }) => {
        const logic = newCategoryLogic({})
        logic.mount()

        typeInto(logic, 'name', 'Product updates')
        handTyped.forEach((key) => typeInto(logic, 'key', key))
        typeInto(logic, 'name', 'Weekly digest')

        expect(logic.values.categoryForm.key).toBe(kept)
    })

    it('follows the name again once the form resets for the next topic', () => {
        const logic = newCategoryLogic({})
        logic.mount()
        typeInto(logic, 'name', 'Product updates')
        typeInto(logic, 'key', 'news')

        logic.actions.resetCategoryForm()
        typeInto(logic, 'name', 'Weekly digest')

        expect(logic.values.categoryForm.key).toBe('weekly-digest')
    })

    it('follows the name again once the hand-typed key is cleared', () => {
        const logic = newCategoryLogic({})
        logic.mount()
        typeInto(logic, 'name', 'Product updates')
        typeInto(logic, 'key', 'news')

        typeInto(logic, 'key', '')
        typeInto(logic, 'name', 'Weekly digest')

        expect(logic.values.categoryForm.key).toBe('weekly-digest')
    })

    it.each([' ', '製品'])('shows no field errors before Create while the name is %j', (name) => {
        const logic = newCategoryLogic({})
        logic.mount()

        typeInto(logic, 'name', name)

        expect(logic.values.categoryFormErrors).toEqual({})
    })

    it('leaves the key alone while workflows-audience is off', () => {
        setAudienceFlag(false)
        const logic = newCategoryLogic({})
        logic.mount()

        typeInto(logic, 'name', 'Product updates')

        expect(logic.values.categoryForm.key).toBe('')
    })

    it.each([
        {
            field: 'key',
            detail: 'A message category with this key already exists.',
            shown: 'Another topic already uses this key',
        },
        {
            field: 'name',
            detail: 'Ensure this field has no more than 128 characters.',
            shown: 'Ensure this field has no more than 128 characters.',
        },
    ])('shows the API error on the $field field, without a toast', async ({ field, detail, shown }) => {
        const toast = jest.spyOn(lemonToast, 'error')
        rejectCreateWith(apiFieldError(field, detail))
        const logic = newCategoryLogic({})
        logic.mount()
        typeInto(logic, 'name', 'Product updates')

        await submitAndFail(logic)

        expect(logic.values.categoryFormAllErrors[field as 'key' | 'name']).toBe(shown)
        expect(toast).not.toHaveBeenCalled()
    })

    it.each([
        { failed: 'key', edited: 'name', value: 'Product news' },
        { failed: 'key', edited: 'key', value: 'product-news' },
        { failed: 'name', edited: 'name', value: 'Product news' },
    ] as const)(
        'clears the API error on the $failed field as soon as the $edited field is edited',
        async ({ failed, edited, value }) => {
            rejectCreateWith(apiFieldError(failed, 'Rejected by the server.'))
            const logic = newCategoryLogic({})
            logic.mount()
            typeInto(logic, 'name', 'Product updates')
            await submitAndFail(logic)

            typeInto(logic, edited, value)

            expect(logic.values.categoryFormErrors).toEqual({})
        }
    )

    it('toasts once when the save fails for a reason no field explains', async () => {
        const toast = jest.spyOn(lemonToast, 'error')
        rejectCreateWith(new ApiError('Server error', 500))
        const logic = newCategoryLogic({})
        logic.mount()
        typeInto(logic, 'name', 'Product updates')

        await submitAndFail(logic)

        expect(toast.mock.calls).toEqual([["Couldn't save the topic. Try again."]])
    })

    it('flag off: an empty key shows only the inline error, no toast', async () => {
        setAudienceFlag(false)
        const toast = jest.spyOn(lemonToast, 'error')
        const create = jest.spyOn(messagingApi, 'messagingCategoriesCreate')
        const logic = newCategoryLogic({})
        logic.mount()
        typeInto(logic, 'name', 'Product updates')

        await submitAndFail(logic)

        expect(logic.values.categoryFormAllErrors.key).toBe('Key is required')
        expect(toast).not.toHaveBeenCalled()
        expect(create).not.toHaveBeenCalled()
    })

    it('never changes the key of an existing topic', () => {
        const logic = newCategoryLogic({ category: BILLING_RECEIPTS })
        logic.mount()

        typeInto(logic, 'name', 'Invoices')

        expect(logic.values.categoryForm.key).toBe('billing-receipts')
    })
})
