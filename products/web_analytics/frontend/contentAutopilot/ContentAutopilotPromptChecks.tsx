import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTable, Link } from '@posthog/lemon-ui'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { ContentAutopilotCheckResultTag } from './ContentAutopilotCheckResultTag'
import { PROMPT_CHECKS_PAGE_SIZE, contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { checkPromptVersion, engineLabel } from './utils'

export const ContentAutopilotPromptChecks = (): JSX.Element => {
    const { checks, checksLoading, checksFailed, checksPage, selectedCheck } = useValues(
        contentAutopilotPromptDetailLogic
    )
    const { selectCheck, setChecksPage } = useActions(contentAutopilotPromptDetailLogic)
    const count = checks?.count ?? 0

    const errorBanner = (
        <LemonBanner type="error" action={{ children: 'Try again', onClick: () => setChecksPage(checksPage) }}>
            Couldn't load the check history. Try again, and if it keeps happening contact support.
        </LemonBanner>
    )

    if (checksFailed && !checks) {
        return errorBanner
    }

    return (
        <div className="flex flex-col gap-2">
            {checksFailed && errorBanner}
            <LemonTable
                size="small"
                dataSource={checks?.results ?? []}
                rowKey="id"
                loading={checksLoading}
                emptyState="No checks yet"
                rowClassName={(check) => (check.id === selectedCheck?.id ? 'bg-surface-secondary' : null)}
                pagination={{
                    controlled: true,
                    pageSize: PROMPT_CHECKS_PAGE_SIZE,
                    currentPage: checksPage,
                    entryCount: count,
                    onForward:
                        checksPage * PROMPT_CHECKS_PAGE_SIZE < count ? () => setChecksPage(checksPage + 1) : undefined,
                    onBackward: checksPage > 1 ? () => setChecksPage(checksPage - 1) : undefined,
                }}
                columns={[
                    {
                        title: 'Checked',
                        key: 'created_at',
                        render: (_, check) => (
                            <Link
                                subtle
                                onClick={() => selectCheck(check)}
                                className="whitespace-nowrap"
                                data-attr="content-autopilot-prompt-check-select"
                            >
                                {humanFriendlyDetailedTime(check.created_at)}
                            </Link>
                        ),
                    },
                    {
                        title: 'Engine',
                        key: 'engine',
                        render: (_, { engine }) => <span className="whitespace-nowrap">{engineLabel(engine)}</span>,
                    },
                    {
                        title: 'Version',
                        key: 'prompt_version',
                        render: (_, check) => checkPromptVersion(check),
                    },
                    {
                        title: 'Result',
                        key: 'result',
                        render: (_, { cited, check_failed }) => (
                            <ContentAutopilotCheckResultTag cited={cited} checkFailed={check_failed} />
                        ),
                    },
                ]}
            />
        </div>
    )
}
