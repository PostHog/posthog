import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { ISSUE_STATUS_OPTIONS } from '../utils'
import { StatusIndicator } from './Indicators'

export const IssueStatusSelect = ({
    status,
    options = ISSUE_STATUS_OPTIONS,
    onChange,
}: {
    status: ErrorTrackingIssue['status']
    options?: ErrorTrackingIssue['status'][]
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element => {
    const [showPopover, setShowPopover] = useState(false)

    const _onChange = (status: ErrorTrackingIssue['status']): void => {
        setShowPopover(false)
        onChange(status)
    }

    return (
        <DropdownMenu open={showPopover} onOpenChange={setShowPopover}>
            <DropdownMenuTrigger
                className="flex items-center hover:bg-fill-button-tertiary-hover p-[0.1rem] rounded cursor-pointer"
                role="button"
            >
                <StatusIndicator status={status} className="ml-1 text-xs text-secondary" />
                <IconChevronDown />
            </DropdownMenuTrigger>
            <IssueStatusDropdown status={status} options={options} onChange={_onChange} />
        </DropdownMenu>
    )
}

function IssueStatusDropdown({
    status,
    options,
    onChange,
}: {
    status: ErrorTrackingIssue['status']
    options: ErrorTrackingIssue['status'][]
    onChange: (status: ErrorTrackingIssue['status']) => void
}): JSX.Element {
    return (
        <DropdownMenuContent>
            <DropdownMenuGroup>
                {options.map((option) => (
                    <DropdownMenuItem
                        key={option}
                        className="text-base text-secondary hover:bg-fill-button-tertiary-hover hover:text-fill-button-tertiary px-1"
                        asChild
                    >
                        <LemonButton
                            fullWidth
                            onClick={() => option !== status && onChange(option)}
                            role="menuitem"
                            size="xsmall"
                            active={option === status}
                        >
                            <StatusIndicator status={option} />
                        </LemonButton>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuGroup>
        </DropdownMenuContent>
    )
}
