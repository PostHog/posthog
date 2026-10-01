import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { spaceSceneLogic } from './spaceSceneLogic'
import { SpaceSettingsSection } from './SpaceSettingsSection'
import { TaskUserAvatar } from './TaskUserAvatar'

export function SpaceMembers({ id }: { id: string }): JSX.Element | null {
    const { space, members, membersLoading, membersUnavailable, creatorId } = useValues(spaceSceneLogic({ id }))
    const { setMemberIds } = useActions(spaceSceneLogic({ id }))
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)

    useOnMountEffect(ensureAllMembersLoaded)

    if (space?.channel_type !== 'private') {
        return null
    }
    const names = new Map<number, string>([
        ...meFirstMembers.map((member) => [member.user.id, fullName(member.user)] as [number, string]),
        ...members.map((member) => [member.id, fullName(member)] as [number, string]),
    ])
    const memberIds = members.map((member) => member.id)
    const allIds = [...new Set([...meFirstMembers.map((member) => member.user.id), ...memberIds])]

    return (
        <SpaceSettingsSection
            label="Members"
            description="Any member can add or remove people. The creator always stays a member."
            action={
                members.length ? (
                    <Text size="xs" variant="muted">
                        {members.length === 1 ? '1 member' : `${members.length} members`}
                    </Text>
                ) : null
            }
        >
            {membersLoading && !members.length ? (
                <Skeleton className="h-24 w-full" />
            ) : membersUnavailable ? (
                <Text size="xs" variant="destructive" role="alert">
                    Couldn’t load members. Reload to try again.
                </Text>
            ) : (
                <div className="flex flex-col gap-2">
                    {/* A multiple picker, so picking a current member again removes them. */}
                    <Combobox
                        multiple
                        items={allIds}
                        value={memberIds}
                        onValueChange={(userIds: number[]) => setMemberIds(userIds)}
                        itemToStringLabel={(userId: number) => names.get(userId) ?? ''}
                        disabled={membersLoading}
                    >
                        <ComboboxInput
                            placeholder="Add people"
                            aria-label="Add people"
                            disabled={membersLoading}
                            data-attr="today-space-settings-members"
                        />
                        <ComboboxContent>
                            <ComboboxEmpty>No one matches that name.</ComboboxEmpty>
                            <ComboboxList>
                                {(userId: number) => (
                                    <ComboboxItem key={userId} value={userId} disabled={userId === creatorId}>
                                        {names.get(userId)}
                                    </ComboboxItem>
                                )}
                            </ComboboxList>
                        </ComboboxContent>
                    </Combobox>
                    <ItemGroup combined>
                        {members.map((member) => {
                            const name = fullName(member)
                            return (
                                <Item
                                    key={member.id}
                                    variant="outline"
                                    size="sm"
                                    data-attr="today-space-settings-member"
                                >
                                    <ItemMedia>
                                        <TaskUserAvatar user={member} />
                                    </ItemMedia>
                                    <ItemContent className="min-w-0">
                                        <ItemTitle className="max-w-full">
                                            <span className="min-w-0 truncate">{name}</span>
                                        </ItemTitle>
                                        {member.email && <ItemDescription>{member.email}</ItemDescription>}
                                    </ItemContent>
                                    <ItemActions>
                                        {member.id === creatorId ? (
                                            <Badge>Creator</Badge>
                                        ) : (
                                            <Tooltip>
                                                <TooltipTrigger
                                                    delay={0}
                                                    render={
                                                        <Button
                                                            size="icon-xs"
                                                            aria-label={`Remove ${name}`}
                                                            disabled={membersLoading}
                                                            onClick={() =>
                                                                setMemberIds(
                                                                    memberIds.filter((userId) => userId !== member.id)
                                                                )
                                                            }
                                                            data-attr="today-space-settings-remove-member"
                                                        />
                                                    }
                                                >
                                                    <IconX />
                                                </TooltipTrigger>
                                                <TooltipContent>
                                                    {membersLoading ? 'Saving your last change' : `Remove ${name}`}
                                                </TooltipContent>
                                            </Tooltip>
                                        )}
                                    </ItemActions>
                                </Item>
                            )
                        })}
                    </ItemGroup>
                </div>
            )}
        </SpaceSettingsSection>
    )
}
