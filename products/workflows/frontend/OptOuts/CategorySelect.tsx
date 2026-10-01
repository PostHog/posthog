import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { optOutCategoriesLogic } from './optOutCategoriesLogic'
import { topicVocabularyLogic } from './topicVocabularyLogic'

export const CategorySelect = ({
    onChange,
    value,
}: {
    onChange: (value: string) => void
    value?: string
}): JSX.Element => {
    const { categories, categoriesLoading } = useValues(optOutCategoriesLogic())
    const { words } = useValues(topicVocabularyLogic)

    return (
        <LemonSelect
            size="small"
            type="tertiary"
            onChange={onChange}
            value={value}
            loading={categoriesLoading}
            disabledReason={!categoriesLoading && !categories.length && words.topicSelect.noTopics}
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
            placeholder={words.topicSelect.placeholder}
        />
    )
}
