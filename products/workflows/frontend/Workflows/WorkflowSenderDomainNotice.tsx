import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { SenderDomainNotice } from './senderDomainNotice'

const domainList = new Intl.ListFormat('en', { type: 'conjunction' })

function noticeMessage(notice: SenderDomainNotice): string {
    if (notice.stage === 'no_domain') {
        return 'No domain configured.'
    }
    const domains = domainList.format(notice.domains)
    const several = notice.domains.length > 1
    return notice.stage === 'waiting'
        ? `Sending starts once ${domains} ${several ? 'are' : 'is'} verified.`
        : `${domains} ${several ? "aren't" : "isn't"} verified yet.`
}

interface WorkflowSenderDomainNoticeProps {
    notice: SenderDomainNotice
    /** Opens the domain setup over the workflow, for the domain's integration or for a new domain. */
    onOpenDomainSetup: (integrationId: number | null) => void
}

function NoticeAction({ notice, onOpenDomainSetup }: WorkflowSenderDomainNoticeProps): JSX.Element {
    if (notice.stage === 'no_domain') {
        return (
            <Link
                onClick={() => onOpenDomainSetup(null)}
                className="shrink-0"
                data-attr="workflow-sender-domain-set-up"
            >
                Set up a domain
            </Link>
        )
    }
    const { integrationId } = notice
    return integrationId === null ? (
        <Link
            to={urls.workflows('channels')}
            target="_blank"
            className="shrink-0"
            data-attr="workflow-sender-domain-status"
        >
            Check domain status
        </Link>
    ) : (
        <Link
            onClick={() => onOpenDomainSetup(integrationId)}
            className="shrink-0"
            data-attr="workflow-sender-domain-status"
        >
            Check domain status
        </Link>
    )
}

export function WorkflowSenderDomainNotice(props: WorkflowSenderDomainNoticeProps): JSX.Element {
    return (
        <span className="flex items-center gap-2 min-w-0 text-xs">
            <span className="text-secondary truncate">{noticeMessage(props.notice)}</span>
            <NoticeAction {...props} />
        </span>
    )
}
