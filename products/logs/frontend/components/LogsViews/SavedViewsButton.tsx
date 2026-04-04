import { useActions } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { logsViewsListLogic } from './logsViewsListLogic'
import { LogsViewsLogicProps } from './logsViewsLogic'
import { SavedViewsModal } from './SavedViewsModal'

interface SavedViewsButtonProps extends LogsViewsLogicProps {
    iconOnly?: boolean
}

function SavedViewsButtonInner({ id, iconOnly }: SavedViewsButtonProps): JSX.Element {
    const { openModal } = useActions(logsViewsListLogic({ id }))

    return (
        <>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconBookmark />}
                onClick={openModal}
                tooltip={iconOnly ? 'Saved views' : undefined}
            >
                {iconOnly ? undefined : 'Saved views'}
            </LemonButton>
            <SavedViewsModal id={id} />
        </>
    )
}

export function SavedViewsButton({ id, iconOnly }: SavedViewsButtonProps): JSX.Element | null {
    const enabled = useFeatureFlag('LOGS_SAVED_VIEWS')

    if (!enabled) {
        return null
    }

    return <SavedViewsButtonInner id={id} iconOnly={iconOnly} />
}
