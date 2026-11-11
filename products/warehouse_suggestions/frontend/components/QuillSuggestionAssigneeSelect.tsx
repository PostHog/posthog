import { useActions, useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    Spinner,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { fullName } from 'lib/utils/strings'

import { membersLogic } from '~/models/membersLogic'
import { UserBasicType } from '~/types'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { EDIT_ACCESS_REASON, SuggestionAssigneeSelectProps } from './SuggestionAssigneeSelect'

const UNASSIGNED = 'unassigned'

export function QuillSuggestionAssigneeSelect({
    suggestionId,
    assignee,
    canAct,
}: SuggestionAssigneeSelectProps): JSX.Element {
    const { actionsInFlight } = useValues(warehouseSuggestionsLogic)
    const { assignSuggestion } = useActions(warehouseSuggestionsLogic)
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const [open, setOpen] = useState(false)
    const triggerRef = useRef<HTMLButtonElement>(null)

    const { usersById, items } = useMemo(() => {
        const usersById: Record<string, UserBasicType> = {}
        const items = [UNASSIGNED]
        for (const { user } of meFirstMembers) {
            usersById[String(user.id)] = user
            items.push(String(user.id))
        }
        return { usersById, items }
    }, [meFirstMembers])

    const setPickerOpen = (next: boolean): void => {
        setOpen(next)
        if (next) {
            ensureAllMembersLoaded()
        }
    }

    return (
        <Combobox<string>
            items={items}
            open={open}
            onOpenChange={setPickerOpen}
            value={assignee ? String(assignee.id) : UNASSIGNED}
            onValueChange={(next: string | null) => {
                assignSuggestion(suggestionId, !next || next === UNASSIGNED ? null : (usersById[next]?.id ?? null))
                setOpen(false)
            }}
            itemToStringLabel={(key: string) =>
                key === UNASSIGNED ? 'Unassigned' : `${fullName(usersById[key])} ${usersById[key]?.email ?? ''}`
            }
        >
            <Button
                ref={triggerRef}
                variant="link-muted"
                size="inline"
                className="text-xs font-normal"
                loading={!!actionsInFlight[suggestionId]}
                disabledReason={canAct ? undefined : EDIT_ACCESS_REASON}
                onClick={() => setPickerOpen(!open)}
                data-attr="warehouse-suggestions-assign"
            >
                {assignee ? `Assigned to ${assignee.first_name || assignee.email}` : 'Assign'}
            </Button>
            <ComboboxContent anchor={triggerRef} className="w-64">
                <ComboboxInput placeholder="Search members…" showTrigger={false} />
                <ComboboxEmpty>
                    {membersLoading ? (
                        <span className="flex items-center gap-2">
                            <Spinner />
                            Loading members…
                        </span>
                    ) : (
                        'No matching members'
                    )}
                </ComboboxEmpty>
                <ComboboxList>
                    {(key: string) =>
                        key === UNASSIGNED ? (
                            <ComboboxItem key={key} value={key}>
                                Unassigned
                            </ComboboxItem>
                        ) : (
                            <ComboboxItem key={key} value={key}>
                                <span className="ph-no-capture flex min-w-0 items-center gap-2">
                                    <QuillPersonAvatar
                                        name={fullName(usersById[key])}
                                        email={usersById[key]?.email}
                                        size="xs"
                                    />
                                    <span className="truncate">{fullName(usersById[key])}</span>
                                </span>
                            </ComboboxItem>
                        )
                    }
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
