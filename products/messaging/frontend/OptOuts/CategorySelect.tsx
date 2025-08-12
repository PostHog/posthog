import { useValues } from 'kea'
import { optOutCategoriesLogic } from './optOutCategoriesLogic'
import { LemonSelect } from '@posthog/lemon-ui'

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
                            labelInMenu: <div className="flex items-center gap-2">{category.name}</div>,
                        })),
                },
                {
                    title: 'Transactional',
                    options: categories
                        .filter((category) => category.category_type === 'transactional')
                        .map((category) => ({
                            label: category.name,
                            value: category.id,
                            labelInMenu: <div className="flex items-center gap-2">{category.name}</div>,
                        })),
                },
            ]}
            placeholder="Select message type"
        />
    )
}
