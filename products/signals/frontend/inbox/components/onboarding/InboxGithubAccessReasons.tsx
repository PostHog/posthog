import type { ReactNode } from 'react'

interface GithubAccessPoint {
    title: string
    description: string
}

interface InboxGithubAccessReasonsProps {
    action?: ReactNode
    // Each caller states its own promise about pull requests. GitHub-optional setup saves PR generation off,
    // but quick setup outside it turns PR generation on. So only the GitHub-optional skip dialog can say that
    // pull requests wait for the user.
    pullRequests: GithubAccessPoint
}

const CODE_ACCESS_POINTS: GithubAccessPoint[] = [
    {
        title: 'Find root causes.',
        description: 'We compare the behavior we see in your product with your code to explain why an issue happens.',
    },
    {
        title: 'Find the change behind a bug.',
        description: 'Commit history lets us point to the pull request that likely introduced it.',
    },
    {
        title: 'Reach the right people.',
        description: 'We assign reports to the teammates who worked on that code.',
    },
]

export function InboxGithubAccessReasons({ action, pullRequests }: InboxGithubAccessReasonsProps): JSX.Element {
    return (
        <>
            <div className="flex items-start justify-between gap-3">
                <p className="m-0 font-semibold text-default">
                    We use GitHub access to research issues and, optionally, open pull requests with proposed fixes.
                </p>
                {action}
            </div>
            <ul className="m-0 flex list-disc flex-col gap-2 pl-4">
                {[...CODE_ACCESS_POINTS, pullRequests].map(({ title, description }) => (
                    <li key={title}>
                        <span className="font-semibold text-default">{title}</span> {description}
                    </li>
                ))}
            </ul>
        </>
    )
}
