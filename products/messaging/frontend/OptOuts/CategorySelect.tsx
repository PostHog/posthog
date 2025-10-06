import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { optOutCategoriesLogic } from './optOutCategoriesLogic'

export const CategorySelect = ({
    onChange,
    value,
}: {
    onChange: (value: string) => void
    value?: string
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
                {
                    title: 'Transactional',
                    options: categories
                        .filter((category) => category.category_type === 'transactional')
                        .map((category) => ({
                            label: category.name,
                            value: category.id,
                        })),
                },
            ]}
            placeholder="Select message type"
        />
    )
}
