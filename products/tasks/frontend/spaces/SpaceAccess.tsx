import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    Combobox,
    ComboboxChip,
    ComboboxChips,
    ComboboxChipsInput,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxValue,
    FieldDescription,
    Label,
    RadioGroup,
    RadioGroupItem,
    Skeleton,
    Text,
} from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { fullName } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceAccess({ id }: { id: string }): JSX.Element | null {
    const { space, savingSpace, members, membersLoading, creatorId } = useValues(spaceSceneLogic({ id }))
    const { updateSpace, setMemberIds } = useActions(spaceSceneLogic({ id }))
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const anchor = useRef<HTMLDivElement>(null)

    useOnMountEffect(ensureAllMembersLoaded)

    if (!space) {
        return null
    }
    if (space.system_role === 'personal') {
        return (
            <Text size="sm" variant="muted">
                Only you can see your personal space.
            </Text>
        )
    }
    const isPrivate = space.channel_type === 'private'
    const generalSpace = space.system_role === 'general'
    const names = new Map<number, string>([
        ...meFirstMembers.map((member) => [member.user.id, fullName(member.user)] as [number, string]),
        ...members.map((member) => [member.id, fullName(member)] as [number, string]),
    ])
    const memberIds = members.map((member) => member.id)
    const allIds = [...new Set([...meFirstMembers.map((member) => member.user.id), ...memberIds])]

    return (
        <div className="flex flex-col gap-3">
            <RadioGroup
                value={isPrivate ? 'private' : 'public'}
                onValueChange={(channelType: 'public' | 'private') => updateSpace({ channel_type: channelType })}
                disabled={generalSpace || savingSpace}
                data-attr="today-space-settings-access"
            >
                <div className="flex items-center gap-2">
                    <RadioGroupItem value="public" id="space-access-public" />
                    <Label htmlFor="space-access-public">Everyone in the project</Label>
                </div>
                <div className="flex items-center gap-2">
                    <RadioGroupItem value="private" id="space-access-private" />
                    <Label htmlFor="space-access-private">Only members</Label>
                </div>
            </RadioGroup>
            {generalSpace && <FieldDescription>The general space is open to everyone in the project.</FieldDescription>}
            {isPrivate &&
                (membersLoading && !members.length ? (
                    <Skeleton className="h-8 w-full max-w-100" />
                ) : (
                    <div className="flex flex-col gap-1">
                        <Combobox
                            multiple
                            items={allIds}
                            value={memberIds}
                            onValueChange={(userIds: number[]) => setMemberIds(userIds)}
                            itemToStringLabel={(userId: number) => names.get(userId) ?? ''}
                        >
                            <ComboboxChips ref={anchor} className="max-w-100" data-attr="today-space-settings-members">
                                <ComboboxValue>
                                    {(userIds: number[]) => (
                                        <>
                                            {userIds.map((userId) =>
                                                userId === creatorId ? (
                                                    <ComboboxChip
                                                        key={userId}
                                                        showRemove={false}
                                                        title={`${names.get(userId) ?? ''} (creator)`}
                                                    >
                                                        <span>{names.get(userId) ?? ''}</span>{' '}
                                                        <Text render={<span />} size="xs" variant="muted">
                                                            Creator
                                                        </Text>
                                                    </ComboboxChip>
                                                ) : (
                                                    <ComboboxChip key={userId}>{names.get(userId) ?? ''}</ComboboxChip>
                                                )
                                            )}
                                            <ComboboxChipsInput placeholder="Add people" aria-label="Add people" />
                                        </>
                                    )}
                                </ComboboxValue>
                            </ComboboxChips>
                            <ComboboxContent anchor={anchor}>
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
                        <FieldDescription>
                            Any member can add or remove people. The creator always stays a member.
                        </FieldDescription>
                    </div>
                ))}
        </div>
    )
}
