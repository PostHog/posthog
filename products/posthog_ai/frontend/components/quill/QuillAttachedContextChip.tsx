import { useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconX } from '@posthog/icons'
import { Chip, ChipClose, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { ContextChip } from '~/layout/ai/chatContextChips'

import { contextItemPath, isOnContextItemPage } from '../../utils/contextItemLink'

export interface QuillAttachedContextChipProps {
    chip: ContextChip
    onRemove?: () => void
}

export function QuillAttachedContextChip({ chip, onRemove }: QuillAttachedContextChipProps): JSX.Element {
    const { label } = chip
    const { location } = useValues(router)
    const path = contextItemPath(chip)
    const onPage = path !== null && isOnContextItemPage(path, location.pathname)

    return (
        <Chip className="max-w-48" data-attr="posthog-ai-context-chip">
            {onRemove && (
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <ChipClose
                                aria-label={`Remove ${label}`}
                                onClick={onRemove}
                                data-attr="posthog-ai-context-chip-remove"
                            />
                        }
                    >
                        <IconX />
                    </TooltipTrigger>
                    <TooltipContent>Remove from chat</TooltipContent>
                </Tooltip>
            )}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        path && !onPage ? (
                            <LinkPrimitive
                                to={path}
                                className="min-w-0 truncate text-inherit hover:underline"
                                onClick={() => {
                                    // pinned: analytics event name
                                    posthog.capture('posthog ai context chip opened', { type: chip.type })
                                }}
                                data-attr="posthog-ai-context-chip-link"
                            />
                        ) : (
                            <span tabIndex={0} className="min-w-0 truncate" />
                        )
                    }
                >
                    {label}
                </TooltipTrigger>
                <TooltipContent>
                    {path === null ? label : onPage ? "You're on this page" : `Open ${label}`}
                </TooltipContent>
            </Tooltip>
        </Chip>
    )
}
