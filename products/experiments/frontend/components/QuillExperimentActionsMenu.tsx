import { Fragment } from 'react'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { useExperimentActions } from 'scenes/experiments/ExperimentView/useExperimentActions'

export function QuillExperimentActionsMenu(): JSX.Element | null {
    const sections = useExperimentActions('actions-dropdown-')

    if (sections.length === 0) {
        return null
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" data-attr="experiment-actions-menu" />}>
                Actions
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
                {sections.map((section, index) => (
                    <Fragment key={section.key}>
                        {index > 0 && <DropdownMenuSeparator />}
                        <DropdownMenuGroup>
                            {section.items.map((item) => (
                                <DropdownMenuItem
                                    key={item['data-attr'] ?? String(item.label)}
                                    variant={item.status === 'danger' ? 'destructive' : 'default'}
                                    onClick={item.onClick}
                                    disabledReason={item.disabledReason}
                                    data-attr={item['data-attr']}
                                >
                                    {item.icon}
                                    {item.label}
                                    {item.sideIcon && <span className="ml-auto">{item.sideIcon}</span>}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuGroup>
                    </Fragment>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
