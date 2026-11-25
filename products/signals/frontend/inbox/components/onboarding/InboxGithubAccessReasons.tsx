import type { ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

interface InboxGithubAccessReasonsProps {
    action?: ReactNode
    className?: string
}

export function InboxGithubAccessReasons({ action, className }: InboxGithubAccessReasonsProps): JSX.Element {
    return (
        <>
            <div className="flex items-start justify-between gap-3">
                <p className="m-0 font-semibold text-default">
                    We use GitHub access to research issues and may automatically open pull requests with proposed
                    fixes.
                </p>
                {action}
            </div>
            <ul className={cn('m-0 list-none p-0', className)}>
                <li>
                    <h4 className="m-0 text-sm font-semibold text-default">Find root causes</h4>
                    <p className="m-0">
                        Code access allows us to accurately identify root causes by comparing the behavior we see in
                        your product with its implementation.
                    </p>
                </li>
                <li>
                    <h4 className="m-0 text-sm font-semibold text-default">Find the change behind a bug</h4>
                    <p className="m-0">
                        Code history allows us to correlate changes in behavior with changes in the code. Our reports
                        are more useful if we can point to a specific PR that may have introduced a user-affecting bug.
                    </p>
                </li>
                <li>
                    <h4 className="m-0 text-sm font-semibold text-default">Reach the right people</h4>
                    <p className="m-0">
                        GitHub commit history lets us assign reports more accurately because we can tell which team
                        members care about an issue.
                    </p>
                </li>
                <li>
                    <h4 className="m-0 text-sm font-semibold text-default">Automatic fixes</h4>
                    <p className="m-0">We can open PRs to fix issues we've researched automatically.</p>
                </li>
            </ul>
        </>
    )
}
