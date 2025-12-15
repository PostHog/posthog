import { useActions } from 'kea'

import { IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { IconLink } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LogMessage } from '~/queries/schema/schema-general'

import { logsLogic } from '../../logsLogic'

interface LogsTableRowActionsProps {
    log: LogMessage
}

export function LogsTableRowActions({ log }: LogsTableRowActionsProps): JSX.Element {
    const { copyLinkToLog } = useActions(logsLogic)

    return (
        <More
            overlay={
                <>
                    <LemonButton
                        onClick={() => copyToClipboard(log.body, 'log message')}
                        fullWidth
                        sideIcon={<IconCopy />}
                        data-attr="logs-table-copy-message"
                    >
                        Copy log message
                    </LemonButton>
                    <LemonButton
                        onClick={() => copyLinkToLog(log.uuid)}
                        fullWidth
                        sideIcon={<IconLink />}
                        data-attr="logs-table-copy-link"
                    >
                        Copy link to log
                    </LemonButton>
                </>
            }
        />
    )
}
