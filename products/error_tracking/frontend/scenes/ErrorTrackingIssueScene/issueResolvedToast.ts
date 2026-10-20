import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import {
    captureMessageAudienceClicked,
    messageAudienceAccessDisabledReason,
} from 'products/workflows/frontend/MessageAudience/messageAudience'
import { openMessageAudience } from 'products/workflows/frontend/MessageAudience/messageAudienceWarnings'

import {
    AFFECTED_LOOKBACK_DAYS,
    IssueAffectedBroadcastLogicProps,
    countAffectedPeople,
    createAffectedPeopleCohort,
    issueFixedAudience,
} from './ScenePanel/issueAffectedBroadcastLogic'

// pinned: sent as the broadcast's entry_source and the click event's source, so renaming it splits the history
const SOURCE = 'error_tracking_resolved'

/** Offers to email the people an issue hit, once, right after someone resolves it. Shows nothing when no one can be emailed. */
export async function showIssueResolvedToast(
    projectId: string,
    issue: IssueAffectedBroadcastLogicProps
): Promise<void> {
    if (messageAudienceAccessDisabledReason()) {
        return
    }
    let withEmail: number
    try {
        withEmail = (await countAffectedPeople(issue.issueId)).withEmail
    } catch {
        return
    }
    if (withEmail === 0) {
        return
    }
    lemonToast.success(
        `Issue resolved. ${pluralize(withEmail, 'person', 'people')} with an email address hit it in the last ${AFFECTED_LOOKBACK_DAYS} days.`,
        {
            button: {
                label: "Tell them it's fixed",
                dataAttr: 'issue-resolved-broadcast',
                action: async () => {
                    captureMessageAudienceClicked(SOURCE, 'broadcast')
                    const startedOn = router.values.location.pathname
                    try {
                        const cohort = await createAffectedPeopleCohort(projectId, issue)
                        if (router.values.location.pathname !== startedOn) {
                            // The person left the page while the cohort saved, so don't pull them into the email.
                            return
                        }
                        await openMessageAudience(issueFixedAudience(cohort, issue, SOURCE), 'broadcast')
                    } catch {
                        lemonToast.error("Couldn't save the people affected. Try again.")
                    }
                },
            },
        }
    )
}
