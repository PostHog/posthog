import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, type LemonButtonProps } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutChatRetryButtonProps } from '../../../utils/scoutChatCta'
import { SCOUT_AUTHOR_PROMPT } from '../../../utils/scoutRunsWindow'

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
    const { runningChatPrompt, failedChatPrompt, scoutChatDisabledReason } = useValues(scoutFleetLogic)
    const isStarting = runningChatPrompt === SCOUT_AUTHOR_PROMPT
    const anotherTaskIsStarting = runningChatPrompt !== null && !isStarting
    const {
        failed: lastAttemptFailed,
        status,
        tooltip,
    } = scoutChatRetryButtonProps(failedChatPrompt, SCOUT_AUTHOR_PROMPT)
    const creationDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmSkill,
        AccessControlLevel.Editor
    )

    return (
        <LemonButton
            type={type}
            size={size}
            status={status}
            tooltip={tooltip}
            icon={<IconSparkles />}
            loading={isStarting}
            disabledReason={
                anotherTaskIsStarting
                    ? 'Starting another task…'
                    : (creationDisabledReason ?? scoutChatDisabledReason ?? undefined)
            }
            onClick={() => startScoutChatTask(SCOUT_AUTHOR_PROMPT, 'scout authoring task', 'Suggest a scout')}
            className={className}
            data-attr={dataAttr}
        >
            {lastAttemptFailed ? 'Try again' : children}
        </LemonButton>
    )
}
