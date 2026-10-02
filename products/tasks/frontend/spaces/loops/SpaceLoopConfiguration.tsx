import { ReactNode } from 'react'

import { Item, ItemActions, ItemContent, ItemGroup, ItemTitle } from '@posthog/quill'

import { SpaceSettingsSection } from '../SpaceSettingsSection'
import { TaskAvatarUser, TaskUserAvatar, taskUserName } from '../TaskUserAvatar'
import { formatScheduleTime } from './form/loopSchedule'
import { SpaceLoop } from './spaceLoopMapping'

function ConfigurationRow({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <Item variant="outline" size="sm">
            <ItemContent>
                <ItemTitle>{label}</ItemTitle>
            </ItemContent>
            <ItemActions className="min-w-0 justify-end text-right text-xs text-muted-foreground">
                {children}
            </ItemActions>
        </Item>
    )
}

export function SpaceLoopConfiguration({
    loop,
    creator,
}: {
    loop: SpaceLoop
    creator: TaskAvatarUser | null
}): JSX.Element {
    return (
        <SpaceSettingsSection label="Configuration">
            <ItemGroup combined>
                <ConfigurationRow label="Model">
                    {[loop.model || 'Default model', loop.reasoningEffort ? `${loop.reasoningEffort} reasoning` : null]
                        .filter(Boolean)
                        .join(' · ')}
                </ConfigurationRow>
                <ConfigurationRow label="Repository">
                    {loop.repositories.length ? loop.repositories.join(', ') : 'None (connector-only loop)'}
                </ConfigurationRow>
                {creator && (
                    <ConfigurationRow label="Created by">
                        <span className="flex items-center gap-2">
                            <TaskUserAvatar user={creator} className="size-5" />
                            <span>{taskUserName(creator)}</span>
                        </span>
                    </ConfigurationRow>
                )}
                <ConfigurationRow label="Triggers">
                    {loop.triggers.length ? (
                        <span className="flex flex-col gap-1">
                            {loop.triggers.map((trigger) => (
                                <span key={trigger}>{trigger}</span>
                            ))}
                            {loop.nextRunAt && (
                                <span>{`Next run ${formatScheduleTime(new Date(loop.nextRunAt), loop.nextRunTimezone)}`}</span>
                            )}
                        </span>
                    ) : (
                        'No triggers configured'
                    )}
                </ConfigurationRow>
                {loop.notifications.length > 0 && (
                    <ConfigurationRow label="Notifications">{loop.notifications.join(', ')}</ConfigurationRow>
                )}
            </ItemGroup>
        </SpaceSettingsSection>
    )
}
