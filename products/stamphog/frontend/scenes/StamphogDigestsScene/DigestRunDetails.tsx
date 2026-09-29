import { useActions } from 'kea'

import { LemonTag, Link } from '@posthog/lemon-ui'

import { DigestRunApi } from '../../generated/api.schemas'
import { digestSlackMessageUrl } from './digestDisplay'
import { stamphogDigestsSceneLogic } from './stamphogDigestsSceneLogic'

export function DigestRunDetails({ run }: { run: DigestRunApi }): JSX.Element {
    const { slackMessageLinkClicked, digestPrLinkClicked } = useActions(stamphogDigestsSceneLogic)
    const slackMessageUrl = digestSlackMessageUrl(run)
    const { headline, prs } = run.summary

    return (
        <div className="flex flex-col gap-3 pl-2 pr-4 py-4 text-xs">
            {run.error && <span className="font-mono text-danger break-all">{run.error}</span>}
            {slackMessageUrl && (
                <Link
                    to={slackMessageUrl}
                    target="_blank"
                    onClick={() => slackMessageLinkClicked(run)}
                    data-attr="stamphog-digest-slack-link"
                >
                    Open in Slack
                </Link>
            )}
            {headline && <p className="m-0 text-sm">{headline}</p>}
            {prs.length > 0 && (
                <ul className="flex flex-col gap-2 m-0 p-0 list-none">
                    {prs.map((pr) => (
                        <li key={pr.url} className="min-w-0">
                            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                                <Link
                                    to={pr.url}
                                    target="_blank"
                                    onClick={() => digestPrLinkClicked(run)}
                                    className="font-semibold break-words min-w-0"
                                    data-attr="stamphog-digest-pr-link"
                                >
                                    #{pr.pr_number} {pr.title}
                                </Link>
                                {pr.repository && <LemonTag type="muted">{pr.repository}</LemonTag>}
                                {pr.author_login && <span className="text-muted">by {pr.author_login}</span>}
                            </div>
                            {pr.summary && <p className="m-0 mt-0.5 text-muted">{pr.summary}</p>}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}
