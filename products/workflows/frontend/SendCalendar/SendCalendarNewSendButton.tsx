import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { sendCalendarLogic } from './sendCalendarLogic'

export function SendCalendarNewSendButton({ day }: { day: string }): JSX.Element {
    const { startNewSend } = useActions(sendCalendarLogic)
    const disabledReason = getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor)

    return (
        <LemonMenu
            items={[
                { label: 'New broadcast', onClick: () => startNewSend('broadcast', day) },
                { label: 'New workflow', onClick: () => startNewSend('workflow', day) },
            ]}
        >
            <LemonButton
                size="xsmall"
                icon={<IconPlus />}
                tooltip="Create a broadcast or workflow"
                disabledReason={disabledReason}
                // Hidden until the day is hovered, so the grid stays calm. Focus shows it for keyboard users.
                className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                data-attr="send-calendar-new-send"
            />
        </LemonMenu>
    )
}
