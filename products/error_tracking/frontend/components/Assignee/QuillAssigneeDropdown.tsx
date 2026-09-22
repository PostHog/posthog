import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useRef } from 'react'

import { IconPlusSmall, IconSearch, IconX } from '@posthog/icons'

import {
    Button,
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    ComboboxListFooter,
    ComboboxTrigger,
    InputGroupAddon,
    Text,
} from 'lib/ui/quill'
import { fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'

import { AssigneeIconDisplay, AssigneeLabelDisplay } from './AssigneeDisplay'
import { Assignee, assigneeSelectLogic, RoleAssignee, UserAssignee } from './assigneeSelectLogic'

const CREATE_ROLE_VALUE = '__create-role__'
const LOADING_ROLES_VALUE = '__loading-roles__'
const LOADING_USERS_VALUE = '__loading-users__'
const OPTION_CLASS_NAME =
    '!ps-2 !pe-8 text-sm [&>span:last-child]:start-auto [&>span:last-child]:end-2 [&>span:last-child>svg]:size-3'

interface AssigneeOptionGroup {
    value: string
    items: string[]
}

export interface QuillAssigneeDropdownProps {
    ariaLabel: string
    assignee: ErrorTrackingIssueAssignee | null
    clearActionLabel: string
    currentUserActionLabel: string
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
    open: boolean
    onOpenChange: (open: boolean) => void
    trigger: JSX.Element
}

function optionValue(assignee: NonNullable<Assignee>): string {
    return `${assignee.type}:${assignee.id}`
}

function optionLabel(assignee: NonNullable<Assignee>): string {
    return assignee.type === 'role' ? assignee.role.name : fullName(assignee.user)
}

export function QuillAssigneeDropdown({
    ariaLabel,
    assignee,
    clearActionLabel,
    currentUserActionLabel,
    onChange,
    open,
    onOpenChange,
    trigger,
}: QuillAssigneeDropdownProps): JSX.Element {
    const { search, filteredRoles, myRoles, filteredMembers, me, rolesLoading, membersLoading } =
        useValues(assigneeSelectLogic)
    const { setSearch } = useActions(assigneeSelectLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)

    const { groups, optionByValue } = useMemo(() => {
        const roles: RoleAssignee[] = filteredRoles.map((role) => ({
            id: role.id,
            type: 'role',
            role,
        }))
        const myRoleIds = new Set(myRoles.map((role) => role.id))
        const myRoleOptions = roles.filter((role) => myRoleIds.has(role.id))
        const otherRoleOptions = roles.filter((role) => !myRoleIds.has(role.id))
        const users: UserAssignee[] = filteredMembers.map((member) => ({
            id: member.user.id,
            type: 'user',
            user: member.user,
        }))
        const options = new Map<string, NonNullable<Assignee>>()

        for (const option of [...roles, ...users]) {
            options.set(optionValue(option), option)
        }

        const myRoleItems = myRoleOptions.map(optionValue)
        const roleItems = otherRoleOptions.map(optionValue)
        if (rolesLoading) {
            roleItems.push(LOADING_ROLES_VALUE)
        } else if (roles.length === 0 && !search) {
            roleItems.push(CREATE_ROLE_VALUE)
        }

        const userItems = users.map(optionValue)
        if (membersLoading) {
            userItems.push(LOADING_USERS_VALUE)
        }

        return {
            groups: [
                { value: 'My roles', items: myRoleItems },
                { value: 'Roles', items: roleItems },
                { value: 'Users', items: userItems },
            ].filter((group) => group.items.length > 0),
            optionByValue: options,
        }
    }, [filteredMembers, filteredRoles, membersLoading, myRoles, rolesLoading, search])

    const selectedValue = assignee ? `${assignee.type}:${assignee.id}` : null
    const isAssignedToMe = assignee?.type === 'user' && assignee.id === me?.user.id

    return (
        <Combobox
            items={groups}
            value={selectedValue}
            inputValue={search}
            open={open}
            autoHighlight
            highlightItemOnHover
            itemToStringLabel={(value) => {
                if (!value) {
                    return ''
                }
                const option = optionByValue.get(value)
                return option ? optionLabel(option) : ''
            }}
            itemToStringValue={(value) => {
                if (!value) {
                    return ''
                }
                const option = optionByValue.get(value)
                return option ? optionLabel(option) : ''
            }}
            onInputValueChange={(value: string) => setSearch(value)}
            onOpenChange={(nextOpen: boolean) => {
                onOpenChange(nextOpen)
                if (!nextOpen) {
                    setSearch('')
                }
            }}
            onValueChange={(value: string | null) => {
                if (!value || value.startsWith('__loading-')) {
                    return
                }
                if (value === CREATE_ROLE_VALUE) {
                    router.actions.push(urls.settings('organization-roles'))
                    return
                }
                const option = optionByValue.get(value)
                if (option) {
                    onChange({ type: option.type, id: option.id })
                }
            }}
        >
            <ComboboxTrigger ref={triggerRef} render={trigger} aria-label={ariaLabel} />
            <ComboboxContent
                anchor={triggerRef}
                align="start"
                className="w-56 [&_[data-slot=combobox-input-group-wrapper]]:border-b-0"
            >
                <ComboboxInput
                    placeholder="Search assignees"
                    autoFocus
                    showTrigger={false}
                    className="h-7 [&_input]:text-sm"
                >
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                </ComboboxInput>
                <ComboboxEmpty className="text-sm">No matches</ComboboxEmpty>
                <ComboboxList>
                    {(group: AssigneeOptionGroup) => (
                        <ComboboxGroup key={group.value} items={group.items}>
                            <ComboboxLabel className="py-1">{group.value}</ComboboxLabel>
                            <ComboboxCollection>
                                {(value: string) => {
                                    if (value === CREATE_ROLE_VALUE) {
                                        return (
                                            <ComboboxItem key={value} value={value} className={OPTION_CLASS_NAME}>
                                                <IconPlusSmall className="size-3" />
                                                Create role
                                            </ComboboxItem>
                                        )
                                    }

                                    if (value === LOADING_ROLES_VALUE || value === LOADING_USERS_VALUE) {
                                        return (
                                            <ComboboxItem
                                                key={value}
                                                value={value}
                                                disabled
                                                className={OPTION_CLASS_NAME}
                                            >
                                                <Text size="sm" variant="muted" className="italic">
                                                    Loading...
                                                </Text>
                                            </ComboboxItem>
                                        )
                                    }

                                    const option = optionByValue.get(value)
                                    if (!option) {
                                        return null
                                    }

                                    return (
                                        <ComboboxItem key={value} value={value} className={OPTION_CLASS_NAME}>
                                            <AssigneeIconDisplay assignee={option} size="xsmall" />
                                            <AssigneeLabelDisplay assignee={option} size="small" />
                                        </ComboboxItem>
                                    )
                                }}
                            </ComboboxCollection>
                        </ComboboxGroup>
                    )}
                </ComboboxList>
                {me || assignee ? (
                    <ComboboxListFooter className="mx-0 mt-0 bg-transparent before:hidden">
                        <div className="flex flex-col gap-0.5">
                            {me && !isAssignedToMe ? (
                                <Button
                                    variant="default"
                                    size="default"
                                    left
                                    className="w-full gap-1.5 text-sm font-medium text-foreground"
                                    onClick={() => onChange({ type: 'user', id: me.user.id })}
                                >
                                    <AssigneeIconDisplay
                                        assignee={{ type: 'user', id: me.user.id, user: me.user }}
                                        size="xsmall"
                                    />
                                    {currentUserActionLabel}
                                </Button>
                            ) : null}
                            {assignee ? (
                                <Button
                                    variant="default"
                                    size="default"
                                    left
                                    className="w-full gap-1.5 text-sm font-medium text-foreground"
                                    onClick={() => onChange(null)}
                                >
                                    <IconX className="size-3" />
                                    {clearActionLabel}
                                </Button>
                            ) : null}
                        </div>
                    </ComboboxListFooter>
                ) : null}
            </ComboboxContent>
        </Combobox>
    )
}
