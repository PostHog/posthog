import { useActions, useValues } from 'kea'

import {
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    RadioGroup,
    RadioGroupItem,
    Text,
    cn,
} from '@posthog/quill'

import { spaceSceneLogic } from './spaceSceneLogic'
import { SpaceSettingsSection } from './SpaceSettingsSection'

const ACCESS_OPTIONS = [
    {
        value: 'public',
        title: 'Everyone in the project',
        description: 'Anyone in this project can see the space and its sessions.',
    },
    {
        value: 'private',
        title: 'Only members',
        description: 'Only the people you add can see the space and its sessions.',
    },
] as const

export function SpaceAccess({ id }: { id: string }): JSX.Element | null {
    const { space, savingSpace } = useValues(spaceSceneLogic({ id }))
    const { updateSpace } = useActions(spaceSceneLogic({ id }))

    if (!space) {
        return null
    }
    if (space.system_role === 'personal') {
        return (
            <SpaceSettingsSection label="Access">
                <Text size="xs" variant="muted" className="px-0.5">
                    Only you can see this personal space.
                </Text>
            </SpaceSettingsSection>
        )
    }
    const generalSpace = space.system_role === 'general'
    const value = space.channel_type === 'private' ? 'private' : 'public'

    return (
        <SpaceSettingsSection
            label="Access"
            description={generalSpace ? 'The general space is open to everyone in the project.' : undefined}
        >
            <RadioGroup
                value={value}
                onValueChange={(channelType: 'public' | 'private') => updateSpace({ channel_type: channelType })}
                disabled={generalSpace || savingSpace}
                className="gap-0"
                data-attr="today-space-settings-access"
            >
                <ItemGroup combined role="none">
                    {ACCESS_OPTIONS.map((option) => (
                        <Item
                            key={option.value}
                            variant="outline"
                            size="sm"
                            className={cn(
                                !generalSpace && 'cursor-pointer',
                                option.value === value && 'bg-fill-selected'
                            )}
                            render={<label htmlFor={`space-access-${option.value}`} />}
                        >
                            <ItemMedia>
                                <RadioGroupItem value={option.value} id={`space-access-${option.value}`} />
                            </ItemMedia>
                            <ItemContent>
                                <ItemTitle>{option.title}</ItemTitle>
                                <ItemDescription>{option.description}</ItemDescription>
                            </ItemContent>
                        </Item>
                    ))}
                </ItemGroup>
            </RadioGroup>
        </SpaceSettingsSection>
    )
}
