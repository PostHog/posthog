import { cn } from 'lib/utils/css-classes'

import type { HogFlowAction } from '../../types'
import { getEmailStepHtml } from '../emailStepHtml'

const EMAIL_LAYOUT_WIDTH = 640

function scaleToWidth(html: string, width: number): string {
    return `<style>html{zoom:${width / EMAIL_LAYOUT_WIDTH};overflow:hidden}</style>${html}`
}

export function EmailStepPreview({
    action,
    emailWidth,
    className,
}: {
    action: HogFlowAction
    emailWidth: number
    className?: string
}): JSX.Element | null {
    const html = getEmailStepHtml(action)
    if (!html) {
        return null
    }

    // sandbox="" disables scripts so the email HTML can't run anything.
    // In dark mode the hue rotation undoes the hue shift of the inversion, so brand colors stay recognizable.
    return (
        <div className={cn('overflow-hidden', className)}>
            <iframe
                title={`Preview of ${action.name}`}
                sandbox=""
                loading="lazy"
                tabIndex={-1}
                srcDoc={scaleToWidth(html, emailWidth)}
                className="pointer-events-none block size-full bg-white dark:invert dark:hue-rotate-180"
                data-attr="workflow-email-step-preview"
            />
        </div>
    )
}
