import { IconCopy } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { LogMessage } from '~/queries/schema/schema-general'

interface LogsTableRowActionsProps {
    log: LogMessage
}

export function LogsTableRowActions({ log }: LogsTableRowActionsProps): JSX.Element {
    return (
        <More
            overlay={
                <>
                    <LemonButton
                        onClick={() => {
                            void copyToClipboard(log.body, 'log message')
                        }}
                        fullWidth
                        sideIcon={<IconCopy />}
                        data-attr="logs-table-copy-message"
                    >
                        Copy log message
                    </LemonButton>
                </>
            }
        />
    )
}
