import { useActions } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { SavedViewsModal } from './SavedViewsModal'
import { tracingViewsListLogic } from './tracingViewsListLogic'

function SavedViewsButtonInner(): JSX.Element {
    const { openModal } = useActions(tracingViewsListLogic)

    return (
        <>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconBookmark />}
                onClick={openModal}
                data-attr="tracing-saved-views-button"
            >
                Saved views
            </LemonButton>
            <SavedViewsModal />
        </>
    )
}

export function SavedViewsButton(): JSX.Element | null {
    const enabled = useFeatureFlag('TRACING_SAVED_VIEWS')

    if (!enabled) {
        return null
    }

    return <SavedViewsButtonInner />
}
