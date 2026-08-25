import { useActions, useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { IconPlusSmall, IconSearch, IconX } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

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
import { Assignee, assigneeSelectLogic } from './assigneeSelectLogic'

const CREATE_ROLE_VALUE = '__create-role__'
const LOADING_ROLES_VALUE = '__loading-roles__'
const LOADING_USERS_VALUE = '__loading-users__'
const OPTION_CLASS_NAME =
    '!ps-2 !pe-8 text-sm [&>span:last-child]:start-auto [&>span:last-child]:end-2 [&>span:last-child>svg]:size-3'

interface AssigneeOptionGroup {
    value: string
    items: string[]
}

export interface AssigneeDropdownProps {
    assignee: ErrorTrackingIssueAssignee | null
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
    open: boolean
    onOpenChange: (open: boolean) => void
    trigger: JSX.Element
    nativeButton: boolean
}

function optionValue(assignee: NonNullable<Assignee>): string {
    return `${assignee.type}:${assignee.id}`
}

function optionLabel(assignee: NonNullable<Assignee>): string {
    return assignee.type === 'role' ? assignee.role.name : fullName(assignee.user)
}

export function AssigneeDropdown({
    assignee,
    onChange,
    open,
    onOpenChange,
    trigger,
    nativeButton,
}: AssigneeDropdownProps): JSX.Element {
    const { search, filteredRoles, filteredMembers, rolesLoading, membersLoading } = useValues(assigneeSelectLogic)
    const { setSearch } = useActions(assigneeSelectLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)

    const { groups, optionByValue } = useMemo(() => {
        const roles: NonNullable<Assignee>[] = filteredRoles.map((role) => ({
            id: role.id,
            type: 'role',
            role,
        }))
        const users: NonNullable<Assignee>[] = filteredMembers.map((member) => ({
            id: member.user.id,
            type: 'user',
            user: member.user,
        }))
        const options = new Map<string, NonNullable<Assignee>>()

        for (const option of [...roles, ...users]) {
            options.set(optionValue(option), option)
        }

        const roleItems = roles.map(optionValue)
        if (rolesLoading) {
            roleItems.push(LOADING_ROLES_VALUE)
        } else if (roleItems.length === 0 && !search) {
            roleItems.push(CREATE_ROLE_VALUE)
        }

        const userItems = users.map(optionValue)
        if (membersLoading) {
            userItems.push(LOADING_USERS_VALUE)
        }

        return {
            groups: [
                { value: 'Roles', items: roleItems },
                { value: 'Users', items: userItems },
            ].filter((group) => group.items.length > 0),
            optionByValue: options,
        }
    }, [filteredMembers, filteredRoles, membersLoading, rolesLoading, search])

    const selectedValue = assignee ? `${assignee.type}:${assignee.id}` : null

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
                if (!value || value === CREATE_ROLE_VALUE || value.startsWith('__loading-')) {
                    return
                }
                const option = optionByValue.get(value)
                if (option) {
                    onChange({ type: option.type, id: option.id })
                }
            }}
        >
            <ComboboxTrigger ref={triggerRef} nativeButton={nativeButton} render={trigger} aria-label="Assignee" />
            <ComboboxContent
                anchor={triggerRef}
                align="start"
                className="w-60 [&_[data-slot=combobox-input-group-wrapper]]:border-b-0"
            >
                <ComboboxInput
                    placeholder="Search assignees"
                    autoFocus
                    showTrigger={false}
                    className="[&_input]:text-sm"
                >
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                </ComboboxInput>
                <ComboboxEmpty className="text-sm">No matches</ComboboxEmpty>
                <ComboboxList>
                    {(group: AssigneeOptionGroup) => (
                        <ComboboxGroup key={group.value} items={group.items}>
                            <ComboboxLabel className="text-sm font-medium normal-case tracking-normal text-muted-foreground">
                                {group.value}
                            </ComboboxLabel>
                            <ComboboxCollection>
                                {(value: string) => {
                                    if (value === CREATE_ROLE_VALUE) {
                                        return (
                                            <ComboboxItem
                                                key={value}
                                                value={value}
                                                className={OPTION_CLASS_NAME}
                                                render={
                                                    <Button
                                                        left
                                                        nativeButton={false}
                                                        className="min-w-0 aria-selected:bg-fill-selected"
                                                        render={<Link to={urls.settings('organization-roles')} />}
                                                    />
                                                }
                                            >
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
                {assignee ? (
                    <ComboboxListFooter className="mx-0 mt-0 border-t-0 bg-transparent before:hidden">
                        <Button
                            variant="default"
                            size="sm"
                            left
                            className="w-full text-sm text-muted-foreground"
                            onClick={() => onChange(null)}
                        >
                            <IconX className="size-3" />
                            Remove assignee
                        </Button>
                    </ComboboxListFooter>
                ) : null}
            </ComboboxContent>
        </Combobox>
    )
}
