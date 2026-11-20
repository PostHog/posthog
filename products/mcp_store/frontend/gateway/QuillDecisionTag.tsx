import { Badge } from '@posthog/quill'

export function QuillDecisionTag({ decision }: { decision: string }): JSX.Element {
    switch (decision) {
        case 'auto':
            return <Badge variant="success">Auto-approved</Badge>
        case 'approved':
            return <Badge variant="completed">Approved</Badge>
        case 'pending':
            return <Badge variant="warning">Awaiting approval</Badge>
        case 'blocked':
            return <Badge variant="destructive">Blocked</Badge>
        default:
            return <Badge>{decision}</Badge>
    }
}
