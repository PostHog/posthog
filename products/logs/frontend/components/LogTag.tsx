import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import { LogMessage } from '~/queries/schema/schema-general'

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
