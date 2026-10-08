import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { optOutCategoriesLogic } from './optOutCategoriesLogic'
import { topicVocabularyLogic } from './topicVocabularyLogic'

export function NewCategoryButton(): JSX.Element {
    const { openNewCategoryModal } = useActions(optOutCategoriesLogic)
    const { words } = useValues(topicVocabularyLogic)

    return (
        <LemonButton
            data-attr="new-optout-category"
            icon={<IconPlusSmall />}
            size="small"
            type="primary"
            onClick={() => openNewCategoryModal()}
        >
            {words.topics.newTopic}
        </LemonButton>
    )
}
