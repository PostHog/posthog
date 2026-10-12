import { IconCheckCircle, IconWarning } from '@posthog/icons'

import type { IdeaEmailSender } from './ideaEmailSender'

/** One checklist line saying whether the project can send an idea's emails yet. */
export function IdeaSenderStep({ sender }: { sender: IdeaEmailSender }): JSX.Element | null {
    if (sender.status === 'verified') {
        return (
            <li className="flex items-start gap-2">
                <IconCheckCircle className="mt-0.5 shrink-0 text-success" />
                <span>
                    Sends from <strong>{sender.address}</strong>
                </span>
            </li>
        )
    }
    if (sender.status === 'unknown') {
        return null
    }
    return (
        <li className="flex items-start gap-2">
            <IconWarning className="mt-0.5 shrink-0 text-warning" />
            <span>
                {sender.status === 'none'
                    ? 'Set up an email sender on your domain. Until then, the workflow can be built but not turned on.'
                    : "Finish verifying your sender's domain. Until then, these emails can't send."}
            </span>
        </li>
    )
}
