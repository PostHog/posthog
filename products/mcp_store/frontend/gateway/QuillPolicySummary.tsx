import { Badge, Text } from '@posthog/quill'

import { MCPToolApprovalStateEnumApi } from '../generated/api.schemas'

export function QuillPolicySummary({ counts }: { counts: Record<MCPToolApprovalStateEnumApi, number> }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <span className="flex items-center gap-1">
                <Badge variant="success">{counts.approved}</Badge>
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    Always allow
                </Text>
            </span>
            <span className="flex items-center gap-1">
                <Badge variant="warning">{counts.needs_approval}</Badge>
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    Needs approval
                </Text>
            </span>
            <span className="flex items-center gap-1">
                <Badge variant="destructive">{counts.do_not_use}</Badge>
                <Text size="xs" variant="muted" render={<span className="m-0" />}>
                    Blocked
                </Text>
            </span>
        </div>
    )
}
