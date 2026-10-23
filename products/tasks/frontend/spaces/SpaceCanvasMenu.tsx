import { useState } from 'react'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'

import { DROPDOWN_PARTS } from '~/layout/today/todayMenuParts'

import type { CanvasApi } from 'products/canvas/frontend/generated/api.schemas'

import { SpaceCanvasActions } from './SpaceCanvasActions'

export function SpaceCanvasMenu({ spaceId, canvas }: { spaceId: string; canvas: CanvasApi }): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon-xs"
                                    aria-label={`More actions for ${canvas.name || 'Untitled canvas'}`}
                                    className={cn(
                                        'relative shrink-0 transition-opacity motion-reduce:transition-none',
                                        open
                                            ? 'opacity-100'
                                            : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100'
                                    )}
                                    data-attr="today-space-canvases-card-menu"
                                />
                            }
                        />
                    }
                >
                    <IconEllipsis />
                </TooltipTrigger>
                <TooltipContent>More actions</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="w-48">
                <SpaceCanvasActions
                    parts={DROPDOWN_PARTS}
                    spaceId={spaceId}
                    canvas={canvas}
                    dataAttrPrefix="today-space-canvases-card-menu"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
