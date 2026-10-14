import { useState } from 'react'

import { Popover } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

import type { InboxSummaryPullRequestApi } from '../../../generated/api.schemas'

export function InboxSummaryPullRequestsPopover({
    pullRequests,
}: {
    pullRequests: InboxSummaryPullRequestApi[]
}): JSX.Element {
    const [visible, setVisible] = useState(false)
    const count = pullRequests.length

    return (
        <Popover
            visible={visible}
            placement="bottom-start"
            showArrow
            padded={false}
            onClickOutside={() => setVisible(false)}
            onMouseEnterInside={() => setVisible(true)}
            onMouseLeaveInside={() => setVisible(false)}
            overlay={
                <div role="dialog" aria-label="Merged pull requests" className="max-h-80 w-80 overflow-y-auto p-2">
                    <p className="m-0 px-1 pb-1 text-xs font-semibold">Merged pull requests</p>
                    <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                        {pullRequests.map((pullRequest) => (
                            <li key={`${pullRequest.repository}#${pullRequest.number}`}>
                                <Link
                                    to={pullRequest.url}
                                    target="_blank"
                                    targetBlankIcon
                                    className="block truncate rounded px-1 py-0.5 text-xs"
                                >
                                    {pullRequest.repository}#{pullRequest.number}
                                </Link>
                            </li>
                        ))}
                    </ul>
                </div>
            }
        >
            <button
                type="button"
                className="m-0 inline cursor-pointer border-0 bg-transparent p-0 font-semibold text-default underline decoration-dotted underline-offset-2 hover:text-accent"
                aria-label={`Show ${count} merged pull ${count === 1 ? 'request' : 'requests'}`}
                aria-haspopup="dialog"
                aria-expanded={visible}
                data-attr="inbox-value-summary-pull-requests"
                onMouseEnter={() => setVisible(true)}
                onMouseLeave={() => setVisible(false)}
                onClick={() => setVisible(!visible)}
            >
                <span>{`${count.toLocaleString()} ${count === 1 ? 'PR' : 'PRs'}`}</span>
            </button>
        </Popover>
    )
}
