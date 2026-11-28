import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { MessageCategory, optOutCategoriesLogic } from './optOutCategoriesLogic'

export const CategorySelect = ({
    onChange,
    value,
    placeholder = 'Select message type',
    transactionalCategories,
}: {
    onChange: (value: string) => void
    value?: string
    placeholder?: string
    /** The transactional categories to offer. All of them when not given. */
    transactionalCategories?: MessageCategory[]
}): JSX.Element => {
    const { categories, categoriesLoading } = useValues(optOutCategoriesLogic())
    const transactional =
        transactionalCategories ?? categories.filter((category) => category.category_type === 'transactional')

    return (
        <LemonSelect
            size="small"
            type="tertiary"
            onChange={onChange}
            value={value}
            loading={categoriesLoading}
            disabledReason={
                !categoriesLoading && !categories.length && 'Configure message categories in the opt-outs section'
            }
            options={[
                {
                    title: 'Marketing',
                    options: categories
                        .filter((category) => category.category_type === 'marketing')
                        .map((category) => ({
                            label: category.name,
                            value: category.id,
                        })),
                },
                ...(transactional.length
                    ? [
                          {
                              title: 'Transactional',
                              options: transactional.map((category) => ({
                                  label: category.name,
                                  value: category.id,
                              })),
                          },
                      ]
                    : []),
            ]}
            placeholder={placeholder}
        />
    )
}
