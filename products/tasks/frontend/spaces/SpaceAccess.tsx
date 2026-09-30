import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'

import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceAccess({ id }: { id: string }): JSX.Element | null {
    const { space, savingSpace, members, membersLoading } = useValues(spaceSceneLogic({ id }))
    const { updateSpace, setMemberIds } = useActions(spaceSceneLogic({ id }))

    if (!space) {
        return null
    }
    if (space.system_role === 'personal') {
        return <span className="text-secondary text-sm">Only you can see your personal space.</span>
    }
    const isPrivate = space.channel_type === 'private'

    return (
        <div className="flex flex-col gap-3">
            <LemonSegmentedButton
                className="self-start"
                size="small"
                value={isPrivate ? 'private' : 'public'}
                onChange={(channelType) => updateSpace({ channel_type: channelType })}
                options={[
                    { value: 'public', label: 'Everyone in the project' },
                    { value: 'private', label: 'Only members' },
                ]}
                disabledReason={
                    space.system_role === 'general'
                        ? 'The general space is open to everyone in the project'
                        : savingSpace
                          ? 'Saving your last change'
                          : undefined
                }
                data-attr="today-space-settings-access"
            />
            {isPrivate &&
                (membersLoading && !members.length ? (
                    <Spinner />
                ) : (
                    <div className="flex flex-col gap-1">
                        <span className="text-secondary text-sm">Any member can add or remove people.</span>
                        <MemberSelectMultiple
                            idKey="id"
                            value={members.map((member) => member.id)}
                            onChange={(users) => setMemberIds(users.map((user) => user.id))}
                        />
                    </div>
                ))}
        </div>
    )
}
