import { useActions } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { logsViewsListLogic } from './logsViewsListLogic'
import { LogsViewsLogicProps } from './logsViewsLogic'
import { SavedViewsModal } from './SavedViewsModal'

function SavedViewsButtonInner({ id }: LogsViewsLogicProps): JSX.Element {
    const { openModal } = useActions(logsViewsListLogic({ id }))

    return (
        <>
            <LemonButton size="small" type="secondary" icon={<IconBookmark />} onClick={openModal}>
                Saved views
            </LemonButton>
            <SavedViewsModal id={id} />
        </>
    )
}

export function SavedViewsButton({ id }: LogsViewsLogicProps): JSX.Element | null {
    const enabled = useFeatureFlag('LOGS_SAVED_VIEWS')

    if (!enabled) {
        return null
    }

    return <SavedViewsButtonInner id={id} />
}
