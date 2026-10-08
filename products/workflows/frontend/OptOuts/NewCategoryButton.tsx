import { useActions } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { optOutCategoriesLogic } from './optOutCategoriesLogic'

export function NewCategoryButton(): JSX.Element {
    const { openNewCategoryModal } = useActions(optOutCategoriesLogic)

    return (
        <LemonButton
            data-attr="new-optout-category"
            icon={<IconPlusSmall />}
            size="small"
            type="primary"
            onClick={() => openNewCategoryModal()}
        >
            New category
        </LemonButton>
    )
}
