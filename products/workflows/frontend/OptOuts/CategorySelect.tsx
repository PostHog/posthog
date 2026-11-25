import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { optOutCategoriesLogic } from './optOutCategoriesLogic'

export const CategorySelect = ({
    onChange,
    value,
    placeholder = 'Select message type',
    allowTransactional = true,
}: {
    onChange: (value: string) => void
    value?: string
    placeholder?: string
    allowTransactional?: boolean
}): JSX.Element => {
    const { categories, categoriesLoading } = useValues(optOutCategoriesLogic())

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
                ...(allowTransactional
                    ? [
                          {
                              title: 'Transactional',
                              options: categories
                                  .filter((category) => category.category_type === 'transactional')
                                  .map((category) => ({
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
