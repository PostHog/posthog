import './QuillInboxTriage.scss'

import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { Button, Heading, Kbd, Skeleton, Text } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { isMac } from 'lib/utils/dom'
import { urls } from 'scenes/urls'

import { inboxTriageLogic } from '../../logics/inboxTriageLogic'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import { QuillTriageCard } from './QuillTriageCard'

const COMMAND_KEY = isMac() ? '⌘' : 'Ctrl'

function Hint({ keys, label }: { keys: string[]; label: string }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1.5">
            {keys.map((key) => (
                <Kbd key={key}>{key}</Kbd>
            ))}
            <span>{label}</span>
        </span>
    )
}

export function QuillInboxTriageView(): JSX.Element {
    const { reports, isLoaded, isRestoringPosition, reportsLoadFailed, currentReport, currentIndex, expanded } =
        useValues(inboxTriageLogic)
    const { ensureLoaded } = useActions(inboxTriageLogic)
    const { count } = useValues(reportListLogic(sectionListLogicProps('needs-decision')))
    const total = Math.max(count ?? 0, reports.length)
    const position = currentReport ? currentIndex + 1 : 0

    return (
        <div className="Today min-h-full flex-1">
            <div className="QuillTriage Today__page" data-quill>
                <div className="flex items-center justify-between">
                    <LinkPrimitive
                        to={urls.inbox('reports')}
                        className="TodayReportNav__back"
                        data-attr="inbox-triage-back"
                    >
                        <IconArrowLeft className="size-3.5" />
                        <span>Inbox</span>
                        <Kbd>Esc</Kbd>
                    </LinkPrimitive>
                    {currentReport && (
                        <Text size="sm" variant="muted" render={<span />} className="tabular-nums" translate="no">
                            {`${position} of ${total}`}
                        </Text>
                    )}
                </div>
                <div
                    className="QuillTriage__progress"
                    role="progressbar"
                    aria-label="Triage progress"
                    aria-valuemin={0}
                    aria-valuemax={total}
                    aria-valuenow={position}
                >
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <span style={{ width: total > 0 ? `${(position / total) * 100}%` : 0 }} />
                </div>
                {!isLoaded && reportsLoadFailed ? (
                    <div className="flex flex-col items-start gap-2 py-10">
                        <Heading size="base" render={<h2 className="m-0" />}>
                            Couldn't load your reports.
                        </Heading>
                        <Button variant="outline" onClick={() => ensureLoaded()} data-attr="inbox-triage-retry">
                            Retry
                        </Button>
                    </div>
                ) : !isLoaded || isRestoringPosition ? (
                    <Skeleton className="h-64 w-full rounded-xl" aria-busy />
                ) : !currentReport ? (
                    <div className="flex flex-col items-start gap-1.5 py-10">
                        <Heading size="base" render={<h2 className="m-0" />}>
                            No reports to triage
                        </Heading>
                        <Text size="sm" variant="muted" render={<p className="m-0" />}>
                            No report needs a decision at this time.
                        </Text>
                        <Button
                            variant="outline"
                            className="mt-2.5"
                            render={<LinkPrimitive to={urls.inbox('reports')} />}
                        >
                            Back to the Inbox
                        </Button>
                    </div>
                ) : (
                    <>
                        <QuillTriageCard key={currentReport.id} report={currentReport} expanded={expanded} />
                        {position < total && <div className="QuillTriage__under" aria-hidden />}
                        <Text size="xs" variant="muted" render={<div />} className="QuillTriage__hints">
                            <Hint keys={['↓']} label="next" />
                            <Hint keys={['↑']} label="previous" />
                            <Hint keys={[COMMAND_KEY, 'U']} label="unclaim" />
                            <Hint keys={['X']} label="remove me as reviewer" />
                        </Text>
                    </>
                )}
            </div>
        </div>
    )
}
