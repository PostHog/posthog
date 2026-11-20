import { match } from 'ts-pattern'

import { Text } from '@posthog/quill'

import { fullName } from 'lib/utils/strings'

import { AssigneeLabelDisplayProps } from './AssigneeDisplay'

export function QuillAssigneeLabelDisplay({
    assignee,
    className,
    placeholder,
}: Omit<AssigneeLabelDisplayProps, 'size'>): JSX.Element {
    return (
        <Text size="xs" render={<span className={className} />}>
            {match(assignee)
                .with({ type: 'role' }, ({ role }) => role.name)
                .with({ type: 'user' }, ({ user }) => <span className="ph-no-capture">{fullName(user)}</span>)
                .otherwise(() => placeholder || 'Unassigned')}
        </Text>
    )
}
