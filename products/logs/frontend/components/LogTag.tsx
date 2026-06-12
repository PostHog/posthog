import { LogMessage } from '@posthog/query-frontend/schema/schema-general'

import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

export const LogTag = ({ level }: { level: LogMessage['severity_text'] }): JSX.Element => {
    const type =
        (
            {
                debug: 'muted',
                info: 'default',
                warn: 'warning',
                error: 'danger',
                fatal: 'danger',
            } as Record<LogMessage['severity_text'], LemonTagType>
        )[level] ?? 'muted'

    return <LemonTag type={type}>{level}</LemonTag>
}
