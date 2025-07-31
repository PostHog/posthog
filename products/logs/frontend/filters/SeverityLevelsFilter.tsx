import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'

import { LogMessage } from '~/queries/schema/schema-general'

import { logsLogic } from '../logsLogic'

const options: Record<LogMessage['severity_text'], string> = {
    trace: 'Trace',
    info: 'Info',
    debug: 'Debug',
    warn: 'Warn',
    error: 'Error',
    fatal: 'Fatal',
}

export const SeverityLevelsFilter = (): JSX.Element => {
    const { severityLevels } = useValues(logsLogic)
    const { setSeverityLevels } = useActions(logsLogic)

    const onClick = (level: LogMessage['severity_text']): void => {
        const levels = [...severityLevels]

        const index = levels.indexOf(level)

        if (index > -1) {
            levels.splice(index, 1)
        } else {
            levels.push(level)
        }

        setSeverityLevels(levels)
    }

    const displayLevels =
        severityLevels.length > 0 ? severityLevels.map((l) => capitalizeFirstLetter(l)).join(', ') : 'All levels'

    return (
        <span className="rounded bg-surface-primary">
            <LemonMenu
                closeOnClickInside={false}
                items={Object.entries(options).map(([key, label]) => ({
                    label,
                    onClick: () => onClick(key as LogMessage['severity_text']),
                    active: severityLevels.includes(key as LogMessage['severity_text']),
                }))}
            >
                <LemonButton icon={<IconFilter />} size="small" type="secondary" className="whitespace-nowrap">
                    {displayLevels}
                </LemonButton>
            </LemonMenu>
        </span>
    )
}
