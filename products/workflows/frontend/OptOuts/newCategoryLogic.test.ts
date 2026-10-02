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

function typeInto(logic: ReturnType<typeof newCategoryLogic.build>, field: 'name' | 'key', value: string): void {
    logic.actions.setCategoryFormValue(field, value)
}

describe('newCategoryLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('slugifies the name into the key of a new topic', () => {
        const logic = newCategoryLogic({})
        logic.mount()

        typeInto(logic, 'name', 'Product updates')

        expect(logic.values.categoryForm.key).toBe('product-updates')
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

    it('never changes the key of an existing topic', () => {
        const logic = newCategoryLogic({ category: BILLING_RECEIPTS })
        logic.mount()

        typeInto(logic, 'name', 'Invoices')

        expect(logic.values.categoryForm.key).toBe('billing-receipts')
    })
})
