import { useValues } from 'kea'

import { LemonCollapse, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function InboxGithubAccessExplanation(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.SELF_DRIVING_GITHUB_ACCESS_EXPLANATION] !== 'test') {
        return null
    }

    return (
        <LemonCollapse
            embedded
            size="small"
            className="w-full"
            panels={[
                {
                    key: 'github-access',
                    dataAttr: 'inbox-github-access-explanation',
                    header: 'Why do we ask for GitHub access?',
                    content: (
                        <div className="text-sm text-secondary">
                            <p className="font-semibold text-default">
                                We will never push to GitHub without your permission.
                            </p>
                            <p>We ask for GitHub access for a few reasons:</p>
                            <ol className="list-decimal pl-5 space-y-3 mb-0">
                                <li>
                                    Code access allows us to accurately identify root causes by comparing the behavior
                                    we see in your product with its implementation.
                                </li>
                                <li>
                                    Code history allows us to correlate changes in behavior with changes in the code.
                                    Our reports are more useful if we can point to a specific PR that may have
                                    introduced a user-affecting bug.
                                </li>
                                <li>
                                    GitHub commit history lets us assign reports more accurately because we can tell
                                    which team members care about an issue.
                                </li>
                                <li>If you enable it, we can open PRs to fix issues we've researched automatically.</li>
                            </ol>
                            <p className="mt-4 mb-0">
                                See our{' '}
                                <Link to="https://posthog.com/docs/self-driving/security" target="_blank">
                                    security docs
                                </Link>{' '}
                                for more information on how we protect your code.
                            </p>
                        </div>
                    ),
                },
            ]}
        />
    )
}
