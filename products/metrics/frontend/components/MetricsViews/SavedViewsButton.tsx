import { useActions } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { metricsViewsListLogic } from './metricsViewsListLogic'
import { SavedViewsModal } from './SavedViewsModal'

function SavedViewsButtonInner(): JSX.Element {
    const { openModal } = useActions(metricsViewsListLogic)

    return (
        <>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconBookmark />}
                onClick={openModal}
                data-attr="metrics-saved-views-button"
            >
                Saved views
            </LemonButton>
            <SavedViewsModal />
        </>
    )
}

export function SavedViewsButton(): JSX.Element | null {
    const enabled = useFeatureFlag('METRICS')

    if (!enabled) {
        return null
    }

    return <SavedViewsButtonInner />
}
