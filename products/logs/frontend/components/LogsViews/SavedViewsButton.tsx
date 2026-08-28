import { useActions } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { logsViewsListLogic } from './logsViewsListLogic'
import { LogsViewsLogicProps } from './logsViewsLogic'
import { SavedViewsModal } from './SavedViewsModal'

interface SavedViewsButtonProps extends LogsViewsLogicProps {
    iconOnly?: boolean
}

export function SavedViewsButton({ id, iconOnly }: SavedViewsButtonProps): JSX.Element {
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
