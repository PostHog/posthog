import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Text,
} from '@posthog/quill'

import { spaceSceneLogic } from './spaceSceneLogic'
import { SpaceSettingsSection } from './SpaceSettingsSection'

type SharedAccess = 'public' | 'private'

const ACCESS: Record<
    SharedAccess,
    { label: string; description: string; action: string; confirmTitle: string; confirmBody: string }
> = {
    public: {
        label: 'Public',
        description: 'Everyone in the project can see this space.',
        action: 'Make private',
        confirmTitle: 'Make this space private?',
        confirmBody: 'Only you and the creator keep access. Other people lose access until you add them as members.',
    },
    private: {
        label: 'Private',
        description: 'Only members can see this space.',
        action: 'Make public',
        confirmTitle: 'Make this space public?',
        confirmBody: 'Everyone in the project gains access to this space and its sessions. The member list is removed.',
    },
}

export function SpaceAccess({ id }: { id: string }): JSX.Element | null {
    const { space, savingSpace, accessConfirmOpen } = useValues(spaceSceneLogic({ id }))
    const { updateSpace, setAccessConfirmOpen } = useActions(spaceSceneLogic({ id }))

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
    const access: SharedAccess = space.channel_type === 'private' ? 'private' : 'public'
    const current = ACCESS[access]

    return (
        <SpaceSettingsSection
            label="Access"
            description={generalSpace ? 'The general space is open to everyone in the project.' : undefined}
        >
            <Item variant="outline" size="sm" data-attr="today-space-settings-access">
                <ItemContent>
                    <ItemTitle>{current.label}</ItemTitle>
                    <ItemDescription>{current.description}</ItemDescription>
                </ItemContent>
                {!generalSpace && (
                    <ItemActions>
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={savingSpace}
                            onClick={() => setAccessConfirmOpen(true)}
                            data-attr="today-space-settings-access-change"
                        >
                            {current.action}
                        </Button>
                    </ItemActions>
                )}
            </Item>
            <AlertDialog
                open={accessConfirmOpen}
                onOpenChange={(open: boolean) => {
                    if (!open && !savingSpace) {
                        setAccessConfirmOpen(false)
                    }
                }}
            >
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>{current.confirmTitle}</AlertDialogTitle>
                        <AlertDialogDescription>{current.confirmBody}</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <Button
                            variant="outline"
                            onClick={() => setAccessConfirmOpen(false)}
                            disabled={savingSpace}
                            data-attr="today-space-settings-access-cancel"
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            loading={savingSpace}
                            disabled={savingSpace}
                            onClick={() => updateSpace({ channel_type: access === 'public' ? 'private' : 'public' })}
                            data-attr="today-space-settings-access-confirm"
                        >
                            {current.action}
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </SpaceSettingsSection>
    )
}
