import { useActions } from 'kea'

import { IconExternal, IconX } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { EmbeddedRunner } from 'products/posthog_ai/frontend/api/runner'

import { commandCenterSceneLogic } from './commandCenterSceneLogic'

export interface CommandCenterSessionTileProps {
    index: number
    sessionId: string
}

export function CommandCenterSessionTile({ index, sessionId }: CommandCenterSessionTileProps): JSX.Element {
    const { clearTile } = useActions(commandCenterSceneLogic)

    return (
        <div className="flex h-full min-h-0 flex-col">
            {/* The tile's own controls sit outside the runner, so they stay when the session fails to load. */}
            <div className="flex h-8 shrink-0 items-center justify-end gap-1 border-b border-[var(--border)] px-1">
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon-sm"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.aiTask(sessionId)} />}
                                aria-label="Open full chat"
                                data-attr="command-center-tile-open"
                            />
                        }
                    >
                        <IconExternal />
                    </TooltipTrigger>
                    <TooltipContent>Open full chat</TooltipContent>
                </Tooltip>
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon-sm"
                                onClick={() => clearTile(index)}
                                aria-label="Remove from tile"
                                data-attr="command-center-tile-remove"
                            />
                        }
                    >
                        <IconX />
                    </TooltipTrigger>
                    <TooltipContent>Remove from tile</TooltipContent>
                </Tooltip>
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                <EmbeddedRunner taskId={sessionId} />
            </div>
        </div>
    )
}
