import { IconPerson } from '@posthog/icons'
import { ProfilePicture } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { fullName, UnexpectedNeverError } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import React, { useMemo } from 'react'
import { match } from 'ts-pattern'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { Assignee, assigneeSelectLogic } from './assigneeSelectLogic'

export interface AssigneeAnyDisplayProps {
    assignee: Assignee
}

export interface AssigneeResolverProps {
    children: (props: { assignee: Assignee }) => React.ReactElement
    assignee: ErrorTrackingIssue['assignee']
}

export const AssigneeResolver = ({ children, assignee }: AssigneeResolverProps): React.ReactElement => {
    const { resolveAssignee } = useValues(assigneeSelectLogic)
    const resolvedAssignee = useMemo(() => resolveAssignee(assignee), [assignee, resolveAssignee])
    return children({ assignee: resolvedAssignee })
}

export interface AssigneeBaseDisplayProps {
    assignee: Assignee
    size?: 'xsmall' | 'small' | 'medium' | 'large'
}

export interface AssigneeIconDisplayProps extends AssigneeBaseDisplayProps {}

function getIconClassname(size: 'xsmall' | 'small' | 'medium' | 'large' = 'medium'): string {
    switch (size) {
        case 'xsmall':
            return 'text-[0.6rem] h-3 w-3'
        case 'small':
            return 'text-[0.75rem] h-4 w-4'
        case 'medium':
            return 'text-[0.85rem] h-5 w-5'
        case 'large':
            return 'text-[1rem] h-6 w-6'
        default:
            throw new UnexpectedNeverError(size)
    }
}

export const AssigneeIconDisplay = ({ assignee, size }: AssigneeIconDisplayProps): JSX.Element => {
    return match(assignee)
        .with({ type: 'role' }, ({ role }) => (
            // The ideal way would be to use a Lettermark component here
            // but there is no way to make it consistent with ProfilePicture at the moment
            // TODO: Make sure the size prop are the same between ProfilePicture and Lettermark
            <ProfilePicture
                user={{ first_name: role.name, last_name: undefined, email: undefined }}
                className={getIconClassname(size)}
            />
        ))
        .with({ type: 'user' }, ({ user }) => <ProfilePicture user={user} className={getIconClassname(size)} />)
        .otherwise(() => (
            <IconPerson
                className={cn(
                    'rounded-full border border-dashed border-secondary text-secondary flex items-center justify-center p-0.5',
                    getIconClassname(size)
                )}
            />
        ))
}

export interface AssigneeLabelDisplayProps extends AssigneeBaseDisplayProps {
    placeholder?: string
    className?: string
}

export const AssigneeLabelDisplay = ({
    assignee,
    className,
    size,
    placeholder,
}: AssigneeLabelDisplayProps): JSX.Element => {
    return (
        <span
            className={cn(className, {
                'text-xs': size === 'xsmall',
                'text-sm': size === 'small',
                'text-base': size === 'medium',
                'text-lg': size === 'large',
            })}
        >
            {match(assignee)
                .with({ type: 'role' }, ({ role }) => role.name)
                .with({ type: 'user' }, ({ user }) => fullName(user))
                .otherwise(() => placeholder || 'Unassigned')}
        </span>
    )
}

interface AssigneeDisplayProps
    extends AssigneeBaseDisplayProps,
        Omit<AssigneeLabelDisplayProps, 'className'>,
        AssigneeIconDisplayProps {
    className?: string
    labelClassname?: string
}

export const AssigneeDisplay = ({
    assignee,
    placeholder,
    className,
    labelClassname,
    size,
}: AssigneeDisplayProps): JSX.Element => {
    return (
        <div className={cn('flex justify-start items-center gap-1', className)}>
            <AssigneeIconDisplay assignee={assignee} size={size} />
            <AssigneeLabelDisplay
                className={labelClassname}
                size={size}
                assignee={assignee}
                placeholder={placeholder}
            />
        </div>
    )
}
