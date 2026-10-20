import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { pluralize, truncate } from 'lib/utils/strings'

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
const MAX_TOAST_NAME_LENGTH = 60

async function tellAffectedPeople(projectId: string, issue: IssueAffectedBroadcastLogicProps): Promise<void> {
    const startedOn = router.values.location.pathname
    try {
        const cohort = await createAffectedPeopleCohort(projectId, issue)
        if (router.values.location.pathname !== startedOn) {
            // The person left the page while the cohort saved, so don't pull them into the email.
            return
        }
        await openMessageAudience(issueFixedAudience(cohort, issue, SOURCE), 'broadcast')
    } catch {
        // Clicking the offer already closed it, so the retry has to live on this toast.
        lemonToast.error("Couldn't save the people affected.", {
            button: {
                label: 'Try again',
                dataAttr: 'issue-resolved-broadcast-retry',
                action: () => tellAffectedPeople(projectId, issue),
            },
        })
    }
}

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
    const resolved = issue.issueName
        ? `Resolved "${truncate(issue.issueName, MAX_TOAST_NAME_LENGTH)}".`
        : 'Issue resolved.'
    lemonToast.success(
        `${resolved} ${pluralize(withEmail, 'person', 'people')} with an email address hit it in the last ${AFFECTED_LOOKBACK_DAYS} days.`,
        {
            // The default id is a hash of the message, so two issues with the same count would share one toast.
            toastId: `issue-resolved-${issue.issueId}`,
            button: {
                label: "Tell them it's fixed",
                dataAttr: 'issue-resolved-broadcast',
                action: async () => {
                    captureMessageAudienceClicked(SOURCE, 'broadcast')
                    await tellAffectedPeople(projectId, issue)
                },
            },
        }
    )
}
