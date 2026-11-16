import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    Avatar,
    AvatarFallback,
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
} from '@posthog/quill'

import { fullNameOrEmail } from 'lib/utils/strings'

import { membersLogic } from '~/models/membersLogic'

import { releaseLogic } from './releaseLogic'
import { ReleaseRow } from './releaseUtils'

const NO_OWNER = 'none'

export function ReleaseOwnerPicker({ row }: { row: ReleaseRow }): JSX.Element {
    const { user } = useValues(releaseLogic)
    const { updateRelease } = useActions(releaseLogic)
    const { meFirstMembers } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const optionLabels = new Map<string, string>([
        ...meFirstMembers.map((member): [string, string] => [
            String(member.user.id),
            member.user.id === user?.id ? `${fullNameOrEmail(member.user)} (you)` : fullNameOrEmail(member.user),
        ]),
        ...(row.owner ? [[NO_OWNER, 'No owner'] as [string, string]] : []),
    ])

    const choose = (value: string | null): void => {
        if (!value) {
            return
        }
        const ownerId = value === NO_OWNER ? null : Number(value)
        if (ownerId === (row.owner?.id ?? null)) {
            return
        }
        updateRelease(row.id, { owner_id: ownerId }, undefined, {
            event: 'release owner changed',
            properties: {
                release_id: row.id,
                change: ownerId === null ? 'cleared' : ownerId === user?.id ? 'assigned to self' : 'assigned to member',
            },
        })
    }

    return (
        <Combobox
            items={[...optionLabels.keys()]}
            value={null}
            onOpenChange={(open: boolean) => open && ensureAllMembersLoaded()}
            onValueChange={choose}
            itemToStringLabel={(value: string) => optionLabels.get(value) ?? value}
            filter={(value: string, query: string) =>
                (optionLabels.get(value) ?? '').toLowerCase().includes(query.trim().toLowerCase())
            }
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={
                    <Button
                        variant={row.owner ? 'default' : 'outline'}
                        size="sm"
                        className="max-w-48 justify-start"
                        data-attr="release-owner-picker"
                    />
                }
            >
                {row.owner ? (
                    <>
                        <Avatar size="xs">
                            <AvatarFallback>{row.owner.first_name.charAt(0).toUpperCase()}</AvatarFallback>
                        </Avatar>
                        <span className="truncate">{row.owner.first_name}</span>
                    </>
                ) : (
                    'Assign owner'
                )}
            </ComboboxTrigger>
            <ComboboxContent anchor={triggerRef} align="end" className="w-64">
                <ComboboxInput placeholder="Search members" aria-label="Search members" showTrigger={false} />
                <ComboboxEmpty>No member matches that search.</ComboboxEmpty>
                <ComboboxList>
                    {(value: string) => (
                        <ComboboxItem key={value} value={value} data-attr="release-owner-option">
                            <span className="truncate">{optionLabels.get(value)}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
