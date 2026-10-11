import { router } from 'kea-router'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import { pluralize, truncate } from 'lib/utils/strings'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import {
    hogFlowsUserBlastRadiusCreate,
    workflowPreviousRecipientsCreate,
} from 'products/workflows/frontend/generated/api'

import { MessageAudience, messageAudienceUrl } from './messageAudience'

const MAX_COHORT_NAME_LENGTH = 200

const HAS_EMAIL: AnyPropertyFilter = {
    key: 'email',
    type: PropertyFilterType.Person,
    operator: PropertyOperator.IsSet,
}

export type PreviousRecipientsCheck =
    | { kind: 'none' }
    | { kind: 'some'; audience: MessageAudience; skipped: number | null }
    | { kind: 'everyone'; skipped: number }
    | { kind: 'failed'; reason: string }

export function previousRecipientsCohortName(audience: MessageAudience): string {
    return truncate(`Already emailed about ${audience.sourceRecordName || 'this'}`, MAX_COHORT_NAME_LENGTH)
}

export function withPreviousRecipientsLeftOut(
    audience: MessageAudience,
    cohort: { id: number; name: string }
): MessageAudience {
    return {
        ...audience,
        properties: [
            ...audience.properties,
            {
                key: 'id',
                type: PropertyFilterType.Cohort,
                value: cohort.id,
                operator: PropertyOperator.NotIn,
                cohort_name: cohort.name,
            },
        ],
    }
}

/** Leaves out the people earlier broadcasts about the same record already emailed, and says who is left. */
export async function checkPreviousRecipients(
    projectId: string,
    audience: MessageAudience,
    // Off for an audience whose cohort is still being filled, where counting it now would read zero.
    { measureOverlap = true }: { measureOverlap?: boolean } = {}
): Promise<PreviousRecipientsCheck> {
    if (!audience.sourceRecord) {
        return { kind: 'none' }
    }
    const cohortName = previousRecipientsCohortName(audience)
    try {
        const previous = await workflowPreviousRecipientsCreate(projectId, {
            source_record: audience.sourceRecord,
            cohort_name: cohortName,
        })
        if (previous.cohort_id === null || previous.people === 0) {
            return { kind: 'none' }
        }
        const narrowed = withPreviousRecipientsLeftOut(audience, { id: previous.cohort_id, name: cohortName })
        if (!measureOverlap) {
            return { kind: 'some', audience: narrowed, skipped: null }
        }
        const [before, after] = await Promise.all(
            [audience, narrowed].map((target) =>
                hogFlowsUserBlastRadiusCreate(projectId, {
                    filters: { properties: [...target.properties, HAS_EMAIL] },
                    dedupe_key: 'email',
                })
            )
        )
        const skipped = Math.max(before.affected - after.affected, 0)
        if (skipped === 0) {
            return { kind: 'none' }
        }
        return after.affected === 0 ? { kind: 'everyone', skipped } : { kind: 'some', audience: narrowed, skipped }
    } catch (error: any) {
        return {
            kind: 'failed',
            reason: typeof error?.detail === 'string' ? error.detail : "Couldn't check who already got this email.",
        }
    }
}

/** Opens the broadcast after the check, asking first when the check leaves nobody or could not run. */
export function openBroadcastAfterCheck(audience: MessageAudience, check: PreviousRecipientsCheck): void {
    const open = (target: MessageAudience): void => router.actions.push(messageAudienceUrl(target, 'broadcast'))
    if (check.kind === 'none') {
        open(audience)
        return
    }
    if (check.kind === 'some') {
        lemonToast.info(
            check.skipped === null
                ? 'People who already got an email about this are left out of the broadcast.'
                : `${pluralize(check.skipped, 'person', 'people')} in this audience already got an email about this, so the broadcast leaves them out.`
        )
        open(check.audience)
        return
    }
    if (check.kind === 'everyone') {
        LemonDialog.open({
            title: 'Everyone here already got this email',
            description:
                check.skipped === 1
                    ? 'The one person in this audience got an email about this before.'
                    : `All ${pluralize(check.skipped, 'person', 'people')} in this audience got an email about this before.`,
            primaryButton: {
                children: 'Email them again',
                onClick: () => open(audience),
                'data-attr': 'message-audience-send-again',
            },
            secondaryButton: { children: 'Cancel' },
        })
        return
    }
    LemonDialog.open({
        title: "Couldn't skip people who already got this email",
        description: `${check.reason} If you continue, people who got an email about this before can get it again.`,
        primaryButton: {
            children: 'Continue anyway',
            onClick: () => open(audience),
            'data-attr': 'message-audience-skip-check-failed-continue',
        },
        secondaryButton: { children: 'Cancel' },
    })
}
