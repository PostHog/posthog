import { useActions, useValues } from 'kea'

import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { humanFriendlyDetailedTime } from 'lib/utils/datetime'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityTable } from './AiVisibilityTable'
import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotCheckResult } from './ContentAutopilotCheckResult'
import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { PROMPT_CHECKS_PAGE_SIZE, contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { checkPromptVersion } from './utils'

export const ContentAutopilotPromptChecks = (): JSX.Element => {
    const { checks, checksLoading, checksFailed, checksPage, selectedCheck } = useValues(
        contentAutopilotPromptDetailLogic
    )
    const { selectCheck, setChecksPage } = useActions(contentAutopilotPromptDetailLogic)
    const count = checks?.count ?? 0

    const errorBanner = (
        <AiVisibilityBanner type="error" action={{ children: 'Try again', onClick: () => setChecksPage(checksPage) }}>
            Couldn't load the check history. Try again, and if it keeps happening contact support.
        </AiVisibilityBanner>
    )

    if (checksFailed && !checks) {
        return errorBanner
    }

    return (
        <div className="flex flex-col gap-2">
            {checksFailed && errorBanner}
            <AiVisibilityTable
                size="small"
                dataSource={checks?.results ?? []}
                rowKey="id"
                loading={checksLoading}
                emptyState="No checks yet"
                rowClassName={(check) => (check.id === selectedCheck?.id ? 'bg-fill-selected' : null)}
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
                            <Button
                                variant="link-foreground"
                                size="sm"
                                onClick={() => selectCheck(check)}
                                className="whitespace-nowrap"
                                data-attr="content-autopilot-prompt-check-select"
                            >
                                {humanFriendlyDetailedTime(check.created_at)}
                            </Button>
                        ),
                    },
                    {
                        title: 'Engine',
                        key: 'engine',
                        render: (_, { engine }) => <ContentAutopilotEngineLabel engine={engine} />,
                    },
                    {
                        title: 'Version',
                        key: 'prompt_version',
                        render: (_, check) => checkPromptVersion(check),
                    },
                    {
                        title: 'Result',
                        key: 'result',
                        render: (_, { mode, cited, check_failed, target_best_position }) =>
                            mode === 'no_search' && !check_failed ? (
                                <Tooltip>
                                    <TooltipTrigger render={<span className="inline-flex" />}>
                                        <AiVisibilityTag type="muted">No search</AiVisibilityTag>
                                    </TooltipTrigger>
                                    <TooltipContent>
                                        This engine answers without searching the web, so it never cites a page.
                                    </TooltipContent>
                                </Tooltip>
                            ) : (
                                <ContentAutopilotCheckResult
                                    cited={cited}
                                    checkFailed={check_failed}
                                    position={target_best_position}
                                />
                            ),
                    },
                ]}
            />
        </div>
    )
}
