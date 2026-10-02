import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

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

function setAudienceFlag(enabled: boolean): void {
    featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_AUDIENCE]: enabled })
}

describe('newCategoryLogic', () => {
    beforeEach(() => {
        initKeaTests()
        setAudienceFlag(true)
    })

    it('slugifies the name into the key of a new topic', () => {
        const logic = newCategoryLogic({})
        logic.mount()

        typeInto(logic, 'name', 'Product updates')

        expect(logic.values.categoryForm.key).toBe('product-updates')
    })

    it.each([
        {
            name: 'Monthly product announcements for engineering and design teams worldwide',
            key: 'monthly-product-announcements-for-engineering-and-design-teams-w',
        },
        { name: `${'a'.repeat(63)} digest`, key: 'a'.repeat(63) },
    ])('cuts the key slugified from a long name to the 64 characters a key can hold: $key', ({ name, key }) => {
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

    it('leaves the key alone while workflows-audience is off', () => {
        setAudienceFlag(false)
        const logic = newCategoryLogic({})
        logic.mount()

        typeInto(logic, 'name', 'Product updates')

        expect(logic.values.categoryForm.key).toBe('')
    })

    it('never changes the key of an existing topic', () => {
        const logic = newCategoryLogic({ category: BILLING_RECEIPTS })
        logic.mount()

        typeInto(logic, 'name', 'Invoices')

        expect(logic.values.categoryForm.key).toBe('billing-receipts')
    })
})
