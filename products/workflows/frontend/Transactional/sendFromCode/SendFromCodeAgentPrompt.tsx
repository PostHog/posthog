import posthog from 'posthog-js'

import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { HedgehogRobot } from '../../Channels/EmailDomain/hoggies'
import { SendFromCodeSurface } from './firstCodeSendLogic'
import { sendFromCodePrompt } from './sendFromCodePrompt'
import { useSendFromCodeTarget } from './useSendFromCodeTarget'

export function SendFromCodeAgentPrompt({
    from,
    surface,
}: {
    from: string | null
    surface: SendFromCodeSurface
}): JSX.Element {
    const { projectToken, ...target } = useSendFromCodeTarget()

    return (
        <div className="flex items-start gap-4" data-attr="send-from-code-agent-prompt">
            <HedgehogRobot className="w-16 shrink-0" />
            <div className="flex flex-col gap-2 min-w-0">
                <p className="m-0 text-sm text-secondary">
                    Paste the prompt into Claude Code, Cursor or another coding agent. It finds where the email belongs
                    in your server code, installs the SDK, adds the send, and tells you how to try it.
                </p>
                <LemonButton
                    type="primary"
                    className="self-start"
                    icon={<IconCopy />}
                    data-attr="send-from-code-copy-agent-prompt"
                    disabledReason={projectToken ? undefined : 'Loading your project'}
                    onClick={() => {
                        if (!projectToken) {
                            return
                        }
                        void copyToClipboard(sendFromCodePrompt({ ...target, projectToken, from }), 'prompt').then(
                            (copied) => {
                                if (copied) {
                                    // pinned: analytics event name
                                    posthog.capture('transactional email agent prompt copied', { surface })
                                }
                            }
                        )
                    }}
                >
                    Copy prompt for your agent
                </LemonButton>
            </div>
        </div>
    )
}
