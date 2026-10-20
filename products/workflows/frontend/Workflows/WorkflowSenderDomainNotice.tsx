import { Link } from '@posthog/lemon-ui'

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

export function WorkflowSenderDomainNotice({ notice }: { notice: SenderDomainNotice }): JSX.Element {
    const setsUpDomain = notice.stage === 'no_domain'
    return (
        <span className="flex items-center gap-2 min-w-0 text-xs">
            <span className="text-secondary truncate">{noticeMessage(notice)}</span>
            <Link
                to={notice.url}
                target="_blank"
                className="shrink-0"
                data-attr={setsUpDomain ? 'workflow-sender-domain-set-up' : 'workflow-sender-domain-status'}
            >
                {setsUpDomain ? 'Set up a domain' : 'Check domain status'}
            </Link>
        </span>
    )
}
