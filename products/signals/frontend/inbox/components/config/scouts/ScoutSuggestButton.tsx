import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, type LemonButtonProps } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'

export interface ScoutSuggestButtonProps {
    children?: React.ReactNode
    className?: string
    size?: LemonButtonProps['size']
    type?: LemonButtonProps['type']
    'data-attr'?: string
}

/** Navigates away to a running cloud task, unlike `ScoutCreateButton`, which opens a modal in place. */
export function ScoutSuggestButton({
    children = 'Suggest a scout',
    className,
    size = 'small',
    type = 'secondary',
    'data-attr': dataAttr,
}: ScoutSuggestButtonProps): JSX.Element {
    const { startScoutChatTask } = useActions(scoutFleetLogic)
    const { runningChatType, aiConsentDisabledReason } = useValues(scoutFleetLogic)
    const isStarting = runningChatType === 'author_scout'
    const anotherTaskIsStarting = runningChatType !== null && !isStarting
    const creationDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmSkill,
        AccessControlLevel.Editor
    )

    return (
        <LemonButton
            type={type}
            size={size}
            icon={<IconSparkles />}
            loading={isStarting}
            disabledReason={
                anotherTaskIsStarting
                    ? 'Starting another task…'
                    : (creationDisabledReason ?? aiConsentDisabledReason ?? undefined)
            }
            onClick={() => startScoutChatTask('author_scout', 'scout authoring task')}
            className={className}
            data-attr={dataAttr}
        >
            {children}
        </LemonButton>
    )
}
