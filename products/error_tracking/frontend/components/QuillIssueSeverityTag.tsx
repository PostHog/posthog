import { Text, cn } from '@posthog/quill'

import { IssueSeverity, issueSeverityIcon, issueSeverityLabel } from './IssueSeverityTag'

function quillIssueSeverityColor(severity: IssueSeverity | null | undefined): string {
    if (severity === 'critical') {
        return 'text-destructive-foreground'
    }
    if (severity === 'high') {
        return 'text-warning-foreground'
    }
    if (severity === 'medium') {
        return 'text-info-foreground'
    }
    return 'text-muted-foreground'
}

export function QuillIssueSeverityTag({
    severity,
    label,
}: {
    severity: IssueSeverity | null | undefined
    label?: string
}): JSX.Element {
    return (
        <Text
            size="xs"
            weight="medium"
            render={<span className={cn('m-0 inline-flex items-center gap-1', quillIssueSeverityColor(severity))} />}
        >
            {issueSeverityIcon(severity)}
            {label ?? issueSeverityLabel(severity)}
        </Text>
    )
}
