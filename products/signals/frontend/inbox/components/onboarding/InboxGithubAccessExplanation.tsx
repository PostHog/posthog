import { useValues } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

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
                                    Code access grounds our research in your code. We can compare the behavior we see in
                                    your product with its implementation to accurately identify root causes.
                                </li>
                                <li>
                                    Code history allows us to correlate changes in behavior with changes in the code.
                                    Our reports are more useful if we can point to a specific PR that may have
                                    introduced a user-affecting bug.
                                </li>
                                <li>
                                    We can route reports to the right people. GitHub commit history helps us make better
                                    guesses about which team members care about an issue and assign the report to them.
                                </li>
                                <li>
                                    We can open PRs to fix issues automatically. If you enable automatic implementation,
                                    we can go directly from finding an issue to fixing it and opening a PR in your
                                    repository.
                                </li>
                            </ol>
                        </div>
                    ),
                },
            ]}
        />
    )
}
