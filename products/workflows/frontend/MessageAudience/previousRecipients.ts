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
// The exclusion is saved before the counts run, so a slow count only costs the number in the toast.
const COUNT_TIMEOUT_MS = 5000
// Saving the exclusion runs on the server inside the request, so it gets longer than the counts.
const RECIPIENTS_TIMEOUT_MS = 20000

function withinTimeout<T>(request: Promise<T>, timeoutMs: number): Promise<T> {
    return Promise.race([
        request,
        new Promise<T>((_, reject) => setTimeout(() => reject(new Error('Timed out')), timeoutMs)),
    ])
}

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
        const previous = await withinTimeout(
            workflowPreviousRecipientsCreate(projectId, {
                source_record: audience.sourceRecord,
                cohort_name: cohortName,
            }),
            RECIPIENTS_TIMEOUT_MS
        )
        if (previous.cohort_id === null || previous.people === 0) {
            return { kind: 'none' }
        }
        const narrowed = withPreviousRecipientsLeftOut(audience, { id: previous.cohort_id, name: cohortName })
        if (!measureOverlap) {
            return { kind: 'some', audience: narrowed, skipped: null }
        }
        let before, after
        try {
            ;[before, after] = await withinTimeout(
                Promise.all(
                    [audience, narrowed].map((target) =>
                        hogFlowsUserBlastRadiusCreate(projectId, {
                            filters: { properties: [...target.properties, HAS_EMAIL] },
                            dedupe_key: 'email',
                        })
                    )
                ),
                COUNT_TIMEOUT_MS
            )
        } catch {
            // The exclusion is saved, so keep it even when the count to show could not be made.
            return { kind: 'some', audience: narrowed, skipped: null }
        }
        // The counts dedupe by email and can sample, so equal counts do not prove nobody overlaps. Keep the exclusion.
        const skipped = Math.max(before.affected - after.affected, 0)
        return after.affected === 0 && skipped > 0
            ? { kind: 'everyone', skipped }
            : { kind: 'some', audience: narrowed, skipped }
    } catch (error: any) {
        return {
            kind: 'failed',
            reason: typeof error?.detail === 'string' ? error.detail : "Couldn't check who already got this email.",
        }
    }
}

/** Opens the broadcast after the check, asking first when the check leaves nobody or could not run. */
export async function openBroadcastAfterCheck(
    audience: MessageAudience,
    check: PreviousRecipientsCheck
): Promise<void> {
    const open = (target: MessageAudience): void => router.actions.push(messageAudienceUrl(target, 'broadcast'))
    if (check.kind === 'none') {
        open(audience)
        return
    }
    if (check.kind === 'some') {
        if (check.skipped === null) {
            lemonToast.info('People who already got an email about this are left out of the broadcast.')
        } else if (check.skipped > 0) {
            lemonToast.info(
                `${pluralize(check.skipped, 'person', 'people')} in this audience already got an email about this, so the broadcast leaves them out.`
            )
        }
        open(check.audience)
        return
    }
    askBeforeOpening(audience, check, open)
}

function askBeforeOpening(
    audience: MessageAudience,
    check: Extract<PreviousRecipientsCheck, { kind: 'everyone' | 'failed' }>,
    open: (target: MessageAudience) => void
): void {
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
