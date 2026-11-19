import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { CyclotronJobInputType } from '~/types'

import { optOutCategoriesLogic } from 'products/workflows/frontend/OptOuts/optOutCategoriesLogic'

// Matches ALL_MARKETING_CATEGORY_ID in the workflows backend, which the messaging product reads as all marketing.
const ALL_MARKETING_CATEGORY_ID = '$all'

export function OptOutOfMessagesConfiguration({
    inputs,
    setInputs,
    error,
}: {
    inputs: Record<string, CyclotronJobInputType>
    setInputs: (inputs: Record<string, CyclotronJobInputType>) => void
    error?: string
}): JSX.Element {
    const { categories, categoriesLoading } = useValues(optOutCategoriesLogic())
    const value = typeof inputs.category_id?.value === 'string' ? inputs.category_id.value : null

    // Transactional sends ignore opt-outs, so only marketing categories can take one.
    const marketingOptions = categories
        .filter((category) => category.category_type === 'marketing')
        .map((category) => ({ label: category.name, value: category.id }))

    return (
        <LemonField.Pure
            label="Message category"
            info="Marketing email, SMS and push steps in this category skip anyone who opted out. Transactional messages still send."
            error={error}
        >
            <LemonSelect<string | null>
                fullWidth
                value={value}
                loading={categoriesLoading}
                onChange={(categoryId) => setInputs({ ...inputs, category_id: { value: categoryId } })}
                options={[
                    { options: [{ label: 'All marketing messages', value: ALL_MARKETING_CATEGORY_ID }] },
                    ...(marketingOptions.length > 0 ? [{ title: 'Marketing', options: marketingOptions }] : []),
                ]}
                placeholder="Choose a message category"
                data-attr="workflow-opt-out-of-messages-category"
            />
        </LemonField.Pure>
    )
}
