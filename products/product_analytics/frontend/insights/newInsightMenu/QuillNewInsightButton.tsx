import { IconPlus } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { Scene } from 'scenes/sceneTypes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function QuillNewInsightButton({
    compact = false,
    overlay,
}: {
    compact?: boolean
    overlay: JSX.Element
}): JSX.Element {
    return (
        <Popover>
            <AccessControlAction
                resourceType={AccessControlResourceType.Insight}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <Shortcut
                    name="NewInsight"
                    keybind={[keyBinds.new]}
                    intent="New insight"
                    interaction="click"
                    scope={Scene.SavedInsights}
                    priority={100}
                >
                    <PopoverTrigger
                        render={
                            <Button
                                variant="primary"
                                data-attr="saved-insights-new-insight-button"
                                tooltip="New insight"
                                aria-label="New insight"
                            />
                        }
                    >
                        <IconPlus />
                        {compact ? <span className="hidden @min-[32rem]/saved-insights:inline">New</span> : 'New'}
                    </PopoverTrigger>
                </Shortcut>
            </AccessControlAction>
            <PopoverContent align="end" className="w-auto p-0">
                {overlay}
            </PopoverContent>
        </Popover>
    )
}
