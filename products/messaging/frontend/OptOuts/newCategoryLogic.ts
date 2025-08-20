import { actions, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { newCategoryLogicType } from './newCategoryLogicType'
import { MessageCategory, optOutCategoriesLogic } from './optOutCategoriesLogic'

export type CategoryForm = {
    name: string
    key: string
    description: string
    public_description: string
    category_type: string
}

export type CategoryLogicProps = {
    category?: MessageCategory | null
    onSuccess?: () => void
}

const NEW_CATEGORY: CategoryForm = {
    name: '',
    key: '',
    description: '',
    public_description: '',
    category_type: 'marketing',
}

export const newCategoryLogic = kea<newCategoryLogicType>([
    path(['products', 'messaging', 'frontend', 'OptOuts', 'newCategoryLogic']),
    props({} as CategoryLogicProps),
    key((props: CategoryLogicProps) => props.category?.id || 'new'),

    actions({
        submitForm: true,
        resetForm: true,
    }),

    forms(({ actions, props }) => ({
        categoryForm: {
            defaults: props.category
                ? {
                      name: props.category.name,
                      key: props.category.key,
                      description: props.category.description,
                      public_description: props.category.public_description,
                      category_type: props.category.category_type,
                  }
                : NEW_CATEGORY,
            errors: ({ name, key }: CategoryForm) => {
                const keyRegex = /^[a-zA-Z0-9_-]+$/
                return {
                    name: !name.trim() ? 'Name is required' : undefined,
                    key: !key.trim()
                        ? 'Key is required'
                        : !keyRegex.test(key)
                          ? 'Only letters, numbers, hyphens (-) & underscores (_) are allowed'
                          : undefined,
                }
            },
            submit: async (formValues: CategoryForm) => {
                if (props.category) {
                    // Update existing category
                    await api.messaging.updateCategory(props.category.id, formValues)
                    lemonToast.success('Category updated successfully')
                } else {
                    // Create new category
                    await api.messaging.createCategory(formValues)
                    lemonToast.success('Category created successfully')
                }
                // Reload categories in the parent logic
                optOutCategoriesLogic.actions.loadCategories()

                actions.resetForm()

                // Trigger success callback if available
                if (props.onSuccess) {
                    props.onSuccess()
                }
            },
        },
    })),

    listeners(({ actions }) => ({
        resetForm: () => {
            actions.resetCategoryForm()
        },
    })),
])
