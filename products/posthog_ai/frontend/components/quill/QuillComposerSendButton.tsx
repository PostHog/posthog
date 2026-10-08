import { forwardRef } from 'react'

import { IconArrowRight, IconStopFilled } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

import { useComposerContext } from '../composer/Composer'

export const QuillComposerSendButton = forwardRef<HTMLSpanElement, { 'data-attr'?: string }>(
    function QuillComposerSendButton({ 'data-attr': dataAttr }, ref): JSX.Element {
        const { sendDisabledReason, loading, stopLoading, showStop, onStop } = useComposerContext()
        const button = showStop ? (
            <Button
                type="button"
                variant="destructive"
                size="icon"
                aria-label="Stop"
                loading={stopLoading}
                onClick={() => onStop?.()}
                data-attr={dataAttr}
            >
                <IconStopFilled />
            </Button>
        ) : (
            <Button
                type="submit"
                variant="primary"
                size="icon"
                className="rounded-xs"
                aria-label="Send message"
                loading={loading}
                disabled={!!sendDisabledReason}
                data-attr={dataAttr}
            >
                <IconArrowRight className="-rotate-90" />
            </Button>
        )
        return (
            <span ref={ref} className="flex">
                <Tooltip>
                    <TooltipTrigger render={button} />
                    <TooltipContent>
                        {showStop ? (stopLoading ? 'Stopping…' : 'Stop') : (sendDisabledReason ?? 'Send message')}
                    </TooltipContent>
                </Tooltip>
            </span>
        )
    }
)
