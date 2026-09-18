import { RRule } from 'rrule'

import { IconLetter } from '@posthog/icons'
import { LemonSelectOption, LemonSelectOptionLeaf, LemonSelectOptions } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { getGrantedScopes } from 'lib/integrations/IntegrationScopesWarning'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { range } from 'lib/utils/arrays'
import { urls } from 'scenes/urls'

import { SubscriptionAIPromptMaxLength, SubscriptionFreeTierLimit } from '~/queries/schema/schema-general'
import { InsightShortId, IntegrationType, SubscriptionResourceTypes, SubscriptionType, WeekdayType } from '~/types'

import IconMicrosoftTeams from 'public/services/microsoft-teams.png'

import {
    type DeliveryConfigApi,
    SubscriptionTargetEnumApi,
    type SubscriptionApi,
} from 'products/subscriptions/frontend/generated/api.schemas'

export const AI_PROMPT_MAX_LENGTH = SubscriptionAIPromptMaxLength.CHARACTERS

const AI_DISPLAY_CONFIG_FIELDS = [
    'include_images',
    'include_feedback',
    'include_manage_link',
    'include_posthog_hint',
] as const satisfies readonly (keyof DeliveryConfigApi)[]

type AiSubscriptionDisplayConfig = Required<Pick<DeliveryConfigApi, (typeof AI_DISPLAY_CONFIG_FIELDS)[number]>>

function aiSubscriptionPostHogHintApplies(targetType?: SubscriptionType['target_type'] | null): boolean {
    return !targetType || targetType === SubscriptionTargetEnumApi.Slack
}

function resolveAiSubscriptionDisplayConfig(
    deliveryConfig: DeliveryConfigApi | null | undefined,
    targetType?: SubscriptionType['target_type'] | null
): AiSubscriptionDisplayConfig {
    return {
        include_images: deliveryConfig?.include_images ?? true,
        include_feedback: deliveryConfig?.include_feedback ?? true,
        include_manage_link: deliveryConfig?.include_manage_link ?? true,
        include_posthog_hint: aiSubscriptionPostHogHintApplies(targetType)
            ? (deliveryConfig?.include_posthog_hint ?? true)
            : false,
    }
}

export type AiSubscriptionDisplayOption = 'images' | 'feedback' | 'posthog_actions'

function summarizeAiSubscriptionDisplayConfig(
    resolved: AiSubscriptionDisplayConfig,
    posthogHintApplies: boolean
): string {
    // Slack renders the manage link and the @PostHog suggestion separately, so a report missing
    // either one is not full. Other targets never get the suggestion, so the link alone is full.
    const allPostHogActions = resolved.include_manage_link && (resolved.include_posthog_hint || !posthogHintApplies)
    const anyPostHogActions = resolved.include_manage_link || resolved.include_posthog_hint

    if (resolved.include_images && resolved.include_feedback && allPostHogActions) {
        return 'Full report'
    }
    if (!resolved.include_images && !resolved.include_feedback && !anyPostHogActions) {
        return 'Report only'
    }

    const includedContent = ['Report']
    if (resolved.include_images) {
        includedContent.push('charts')
    }
    if (resolved.include_feedback) {
        includedContent.push('feedback')
    }
    if (resolved.include_manage_link && resolved.include_posthog_hint) {
        includedContent.push('PostHog links and suggestions')
    } else if (resolved.include_manage_link) {
        includedContent.push('manage link')
    } else if (resolved.include_posthog_hint) {
        includedContent.push('PostHog suggestion')
    }

    return includedContent.join(' + ')
}

export function getAiSubscriptionDisplaySummary(
    deliveryConfig: DeliveryConfigApi | null | undefined,
    targetType?: SubscriptionType['target_type'] | null
): string {
    const resolved = resolveAiSubscriptionDisplayConfig(deliveryConfig, targetType)
    return summarizeAiSubscriptionDisplayConfig(resolved, aiSubscriptionPostHogHintApplies(targetType))
}

export function getAiSubscriptionDisplayOptionState(
    deliveryConfig: DeliveryConfigApi | null | undefined,
    option: AiSubscriptionDisplayOption
): boolean {
    const resolved = resolveAiSubscriptionDisplayConfig(deliveryConfig)

    if (option === 'images') {
        return resolved.include_images
    }
    if (option === 'feedback') {
        return resolved.include_feedback
    }
    return resolved.include_manage_link || resolved.include_posthog_hint
}

export function updateAiSubscriptionDisplayOption(
    deliveryConfig: DeliveryConfigApi | null | undefined,
    option: AiSubscriptionDisplayOption,
    enabled: boolean
): DeliveryConfigApi {
    if (option === 'images') {
        return { ...deliveryConfig, include_images: enabled }
    }
    if (option === 'feedback') {
        return { ...deliveryConfig, include_feedback: enabled }
    }
    return { ...deliveryConfig, include_manage_link: enabled, include_posthog_hint: enabled }
}

export function requestSubscriptionWizardCancellation({
    onCancel,
    resetSubscription,
    subscriptionChanged,
}: {
    onCancel: () => void
    resetSubscription: () => void
    subscriptionChanged: boolean
}): void {
    if (!subscriptionChanged) {
        onCancel()
        return
    }

    LemonDialog.open({
        title: 'Discard subscription changes?',
        description: 'Your subscription configuration will be lost.',
        primaryButton: {
            children: 'Discard changes',
            status: 'danger',
            onClick: () => {
                resetSubscription()
                onCancel()
            },
        },
        secondaryButton: {
            children: 'Keep editing',
        },
    })
}

export function isFreeTierCreateAtLimit(subscriptionCount: number | null): boolean {
    return subscriptionCount !== null && subscriptionCount >= SubscriptionFreeTierLimit.COUNT
}

export function canNudgeToSubscribe(
    hasSubscriptionsFeature: boolean,
    freeTierSubscriptionCount: number | null
): boolean {
    return (
        hasSubscriptionsFeature ||
        (freeTierSubscriptionCount !== null && !isFreeTierCreateAtLimit(freeTierSubscriptionCount))
    )
}

export interface SubscriptionBaseProps {
    dashboardId?: number
    insightShortId?: InsightShortId
}

export type SubscriptionsLogicProps = SubscriptionBaseProps

export const urlForSubscriptions = ({ dashboardId, insightShortId }: SubscriptionBaseProps): string => {
    if (insightShortId) {
        return urls.insightSubcriptions(insightShortId)
    } else if (dashboardId) {
        return urls.dashboardSubscriptions(dashboardId)
    }
    // Parent-less (e.g. AI prompt) subscriptions live at the top-level list.
    return urls.subscriptions()
}

export const urlForSubscription = (
    id: number | 'new',
    { dashboardId, insightShortId }: SubscriptionBaseProps
): string => {
    if (insightShortId) {
        return urls.insightSubcription(insightShortId, id.toString())
    } else if (dashboardId) {
        return urls.dashboardSubscription(dashboardId, id.toString())
    }
    // Parent-less (e.g. AI prompt) subscriptions: top-level detail/new page.
    return id === 'new' ? urls.subscriptionNew() : urls.subscription(id)
}

export const targetTypeOptions: LemonSelectOptionLeaf<SubscriptionApi['target_type']>[] = [
    { value: SubscriptionTargetEnumApi.Email, label: 'Email', icon: <IconLetter /> },
    { value: SubscriptionTargetEnumApi.Slack, label: 'Slack', icon: <IconSlack /> },
    {
        value: SubscriptionTargetEnumApi.Teams,
        label: 'Microsoft Teams',
        icon: <img src={IconMicrosoftTeams} alt="" className="h-4 w-4" />,
    },
]

export const intervalOptions: LemonSelectOptions<number> = range(1, 13).map((x) => ({ value: x, label: x.toString() }))

export type FrequencyOptionValue = 'daily' | 'weekly' | 'monthly'

export function shouldShowDayPicker(frequency: SubscriptionType['frequency'], interval: number): boolean {
    return frequency === 'weekly' || (frequency === 'daily' && interval === 1)
}

export const frequencyOptionsSingular: LemonSelectOption<FrequencyOptionValue>[] = [
    { value: 'daily', label: 'day' },
    { value: 'weekly', label: 'week' },
    { value: 'monthly', label: 'month' },
]
export const frequencyOptionsPlural: LemonSelectOption<FrequencyOptionValue>[] = [
    { value: 'daily', label: 'days' },
    { value: 'weekly', label: 'weeks' },
    { value: 'monthly', label: 'months' },
]

export const weekdayOptions = [
    { value: 'monday', label: 'Monday' },
    { value: 'tuesday', label: 'Tuesday' },
    { value: 'wednesday', label: 'Wednesday' },
    { value: 'thursday', label: 'Thursday' },
    { value: 'friday', label: 'Friday' },
    { value: 'saturday', label: 'Saturday' },
    { value: 'sunday', label: 'Sunday' },
] satisfies LemonSelectOptionLeaf<WeekdayType>[]

export const ALL_DAYS = weekdayOptions.map(({ value }) => value)
export const WEEKDAY_DAYS = ALL_DAYS.slice(0, 5)
export const WEEKEND_DAYS = ALL_DAYS.slice(5)

export const WEEKDAYS: Set<string> = new Set(WEEKDAY_DAYS)

function hasSameDays(selectedDays: WeekdayType[], presetDays: WeekdayType[]): boolean {
    const selectedSet = new Set(selectedDays)
    return selectedSet.size === presetDays.length && presetDays.every((day) => selectedSet.has(day))
}

export function selectedDaysToDayPickerLabel(selectedDays: WeekdayType[]): string {
    if (selectedDays.length === 0) {
        return 'Select at least one day'
    }
    if (hasSameDays(selectedDays, ALL_DAYS)) {
        return 'on Monday to Sunday'
    }
    if (hasSameDays(selectedDays, WEEKDAY_DAYS)) {
        return 'on weekdays'
    }
    if (hasSameDays(selectedDays, WEEKEND_DAYS)) {
        return 'on weekends'
    }
    if (selectedDays.length === 1) {
        const dayLabel = weekdayOptions.find(({ value }) => value === selectedDays[0])?.label ?? selectedDays[0]
        return `on ${dayLabel}`
    }
    return `on ${selectedDays.length} days`
}

export function formatSubscriptionSchedule(
    subscription: Pick<SubscriptionType, 'frequency' | 'interval' | 'start_date' | 'byweekday'>
): string {
    const frequency =
        subscription.interval === 1
            ? { daily: 'day', weekly: 'week', monthly: 'month', yearly: 'year' }[subscription.frequency]
            : subscription.frequency
    const selectedDays = shouldShowDayPicker(subscription.frequency, subscription.interval)
        ? ` ${formatSelectedDeliveryDays(subscription.byweekday ?? [])}`
        : ''

    return `Every ${subscription.interval} ${frequency}${selectedDays} at ${dayjs(subscription.start_date).format('h:mm A')}`
}

export function getSubscriptionAdvancedSettings(
    subscription: Pick<SubscriptionType, 'summary_enabled' | 'summary_prompt_guide' | 'send_test_now'>
): string[] {
    const settings: string[] = []

    if (subscription.summary_enabled) {
        settings.push('Automatic AI summary')
    }
    if (subscription.summary_prompt_guide?.trim()) {
        settings.push('Custom AI summary context')
    }
    if (subscription.send_test_now === false) {
        settings.push('No test delivery')
    }

    return settings
}

export function integrationHasFilesWrite(integration: IntegrationType | null | undefined): boolean {
    return integration ? getGrantedScopes(integration).includes('files:write') : false
}

/**
 * The API accepts the AI display options on prompt subscriptions only. Toggling resource_type
 * back to insight or dashboard leaves them in form state, so drop them here rather than let the
 * save fail on options the non-AI form no longer shows.
 */
function dropAiDisplayConfigForNonAi(subscription: SubscriptionType): SubscriptionType['delivery_config'] {
    const deliveryConfig = subscription.delivery_config
    if (subscription.resource_type === SubscriptionResourceTypes.AiPrompt || !deliveryConfig) {
        return deliveryConfig
    }
    if (!AI_DISPLAY_CONFIG_FIELDS.some((field) => field in deliveryConfig)) {
        return deliveryConfig
    }

    const remaining = { ...deliveryConfig }
    for (const field of AI_DISPLAY_CONFIG_FIELDS) {
        delete remaining[field]
    }
    return remaining
}

export function coerceDeliveryConfigForScope(
    subscription: SubscriptionType,
    integrations: IntegrationType[] | null | undefined
): SubscriptionType['delivery_config'] {
    const deliveryConfig = dropAiDisplayConfigForNonAi(subscription)
    if (!deliveryConfig?.post_all_insights_in_main_message) {
        return deliveryConfig
    }
    // A prompt report always posts its charts in the main message, so the API rejects this option
    // and the form hides its toggle. Without this the stored flag has no control that can clear it.
    if (subscription.resource_type === SubscriptionResourceTypes.AiPrompt) {
        return { ...deliveryConfig, post_all_insights_in_main_message: false }
    }
    if (subscription.target_type !== 'slack') {
        return { ...deliveryConfig, post_all_insights_in_main_message: false }
    }
    if (integrations == null) {
        return deliveryConfig
    }

    const selectedIntegration = subscription.integration_id
        ? integrations.find((integration) => integration.id === subscription.integration_id)
        : undefined
    if (!integrationHasFilesWrite(selectedIntegration)) {
        return { ...deliveryConfig, post_all_insights_in_main_message: false }
    }
    return deliveryConfig
}

function formatSelectedDeliveryDays(selectedDays: WeekdayType[]): string {
    if (hasSameDays(selectedDays, ALL_DAYS)) {
        return 'on Monday to Sunday'
    }
    if (hasSameDays(selectedDays, WEEKDAY_DAYS)) {
        return 'on weekdays'
    }
    if (hasSameDays(selectedDays, WEEKEND_DAYS)) {
        return 'on weekends'
    }

    const labels = weekdayOptions.filter((day) => selectedDays.includes(day.value)).map((day) => day.label)
    if (labels.length < 2) {
        return labels.length ? `on ${labels[0]}` : 'on no days'
    }
    if (labels.length === 2) {
        return `on ${labels[0]} and ${labels[1]}`
    }

    return `on ${labels.slice(0, -1).join(', ')}, and ${labels[labels.length - 1]}`
}

export function toggleSelectedDay(selectedDays: WeekdayType[], day: WeekdayType): WeekdayType[] {
    const nextDays = new Set(selectedDays)
    if (nextDays.has(day)) {
        nextDays.delete(day)
    } else {
        nextDays.add(day)
    }
    return ALL_DAYS.filter((weekday) => nextDays.has(weekday))
}

export const monthlyWeekdayOptions: LemonSelectOptions<
    'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday' | 'day' | 'weekday'
> = [...weekdayOptions, { value: 'day', label: 'day' }, { value: 'weekday', label: 'weekday' }]

export const bysetposOptions: LemonSelectOptions<'1' | '2' | '3' | '4' | '-1'> = [
    { value: '1', label: 'first' },
    { value: '2', label: 'second' },
    { value: '3', label: 'third' },
    { value: '4', label: 'fourth' },
    { value: '-1', label: 'last' },
]

export const timeOptions: LemonSelectOptions<string> = range(0, 24).map((x) => ({
    value: String(x),
    label: `${x % 12 || 12}:00 ${x < 12 ? 'AM' : 'PM'}`,
}))

const RRULE_WEEKDAY_MAP: Record<string, (typeof RRule)['MO']> = {
    monday: RRule.MO,
    tuesday: RRule.TU,
    wednesday: RRule.WE,
    thursday: RRule.TH,
    friday: RRule.FR,
    saturday: RRule.SA,
    sunday: RRule.SU,
}

const RRULE_FREQ_MAP: Record<string, number> = {
    daily: RRule.DAILY,
    weekly: RRule.WEEKLY,
    monthly: RRule.MONTHLY,
    yearly: RRule.YEARLY,
}

// Client-side preview only — the authoritative next delivery date is computed
// server-side in posthog/models/subscription.py (Subscription.set_next_delivery_date)
export function getNextDeliveryDate(subscription: Partial<SubscriptionType>, timezone?: string): Date | null {
    if (!subscription.frequency || !subscription.start_date) {
        return null
    }
    try {
        // Mirror of Subscription.set_next_delivery_date: the recurrence is anchored to the
        // local wall-clock time of start_date in the project timezone and each occurrence is
        // read back in that timezone, keeping the delivery at the same local time across DST
        // transitions. rrule.js operates on the UTC fields of the dates it is given, so
        // wall-clock fields are carried through pseudo-UTC Dates. Without a timezone the
        // historical UTC-anchored behavior is kept.
        const wallStart = timezone ? dayjs(subscription.start_date).tz(timezone) : dayjs(subscription.start_date).utc()
        // Widen the wall-time window beyond any tzdb offset shift: the wall occurrence
        // whose later fold is still ahead can sit behind now on the wall clock by up to
        // the size of the shift, so the rrule must start before it and the candidate
        // filtering below decides purely by instant. 26h covers every shift in tzdb,
        // including whole-day dateline skips, where 2h would silently drop multi-hour
        // folds. Mirrors Subscription._compute_next_delivery_date.
        const wallNow = timezone ? dayjs(Date.now() - 26 * 3600000).tz(timezone) : dayjs().utc()
        // Whole-second precision, matching dateutil's rrule on the backend: it truncates
        // microseconds, so the pseudo-UTC dates do the same or the two stacks disagree
        // inside sub-second windows.
        const toPseudoUtc = (d: dayjs.Dayjs): Date =>
            new Date(Date.UTC(d.year(), d.month(), d.date(), d.hour(), d.minute(), d.second()))
        const rule = new RRule({
            freq: RRULE_FREQ_MAP[subscription.frequency],
            interval: subscription.interval ?? 1,
            dtstart: toPseudoUtc(wallStart),
            byweekday: subscription.byweekday?.map((d) => RRULE_WEEKDAY_MAP[d]) ?? null,
            bysetpos: subscription.frequency === 'monthly' ? (subscription.bysetpos ?? null) : null,
        })
        const next = rule.after(toPseudoUtc(wallNow))
        if (!next || !timezone) {
            return next
        }
        // Compare in instants, not wall time: an ambiguous occurrence (repeated hour after
        // a fall-back) exists twice and the earlier instant may already be past, while a
        // nonexistent occurrence (spring-forward gap) falls forward using the pre-transition
        // offset. Mirrors Subscription._compute_next_delivery_date.
        const wallMsOf = (instant: number): number => {
            const d = dayjs(instant).tz(timezone)
            return Date.UTC(d.year(), d.month(), d.date(), d.hour(), d.minute(), d.second(), d.millisecond())
        }
        const offsetAt = (instant: number): number => wallMsOf(instant) - instant
        // Enumerate every UTC offset in effect in a broad window around the wall time.
        // Scanning offset changes directly (instead of probing +/-1h around found matches)
        // keeps multi-hour folds like Antarctica/Troll's two-hour fall-back reachable and
        // finds the pre-transition offset on positive-offset transition days, where the
        // wall time as UTC already sits past the change and match-driven probing dead-ends.
        const OFFSET_SCAN_WINDOW_MS = 26 * 3600000
        const OFFSET_SCAN_STEP_MS = 15 * 60000
        const scanOffsetChanges = (
            wall: number,
            onChange: (instant: number, before: number, after: number) => void
        ): void => {
            let prevT = wall - OFFSET_SCAN_WINDOW_MS
            let prevOffset = offsetAt(prevT)
            for (let t = prevT + OFFSET_SCAN_STEP_MS; t <= wall + OFFSET_SCAN_WINDOW_MS; t += OFFSET_SCAN_STEP_MS) {
                const offset = offsetAt(t)
                if (offset !== prevOffset) {
                    // Bisect to whole-second precision: the first instant with the new offset.
                    let lo = prevT
                    let hi = t
                    while (hi - lo > 1000) {
                        const mid = Math.floor((lo + hi) / 2)
                        if (offsetAt(mid) === prevOffset) {
                            lo = mid
                        } else {
                            hi = mid
                        }
                    }
                    onChange(hi, prevOffset, offset)
                    prevOffset = offset
                }
                prevT = t
            }
        }
        const offsetsAround = (wall: number): Set<number> => {
            const offsets = new Set<number>([offsetAt(wall - OFFSET_SCAN_WINDOW_MS)])
            scanOffsetChanges(wall, (_instant, _before, after) => offsets.add(after))
            return offsets
        }
        const wallToInstants = (wall: number): number[] => {
            const instants: number[] = []
            for (const offset of offsetsAround(wall)) {
                const instant = wall - offset
                if (wallMsOf(instant) === wall && !instants.includes(instant)) {
                    instants.push(instant)
                }
            }
            return instants.sort((a, b) => a - b)
        }
        // A nonexistent wall time (spring-forward gap) has no matching instant: deliver at
        // the pre-transition offset, i.e. as soon as the local clock jumps past it, the
        // same normalization zoneinfo's fold=0 applies on the backend.
        const preGapOffset = (wall: number): number | null => {
            let found: number | null = null
            scanOffsetChanges(wall, (instant, before, after) => {
                if (after > before && wall >= instant + before && wall < instant + after) {
                    found = before
                }
            })
            return found
        }
        const pseudoFieldsOf = (d: Date): number =>
            Date.UTC(
                d.getUTCFullYear(),
                d.getUTCMonth(),
                d.getUTCDate(),
                d.getUTCHours(),
                d.getUTCMinutes(),
                d.getUTCSeconds()
            )

        const lower = Date.now()
        let occurrence: Date | null = next
        while (occurrence) {
            const wall = pseudoFieldsOf(occurrence)
            let candidates = wallToInstants(wall)
            if (candidates.length === 0) {
                candidates = [wall - (preGapOffset(wall) ?? offsetAt(wall))]
            }
            const upcoming = candidates.find((instant) => instant > lower)
            if (upcoming !== undefined) {
                return new Date(upcoming)
            }
            occurrence = rule.after(occurrence, false)
        }
        return null
    } catch {
        return null
    }
}

export interface AiSubscriptionGateInputs {
    isAiPrompt: boolean
    isParentless: boolean
    isEditing: boolean
    aiConsentApproved: boolean
    isCloud: boolean
    isDebug: boolean
    aiFlagEnabled: boolean
}

export interface AiSubscriptionGate {
    /** Org cleared every gate (consent + cloud/debug + flag) needed to author an AI report. */
    aiAllowed: boolean
    /** Show the "What to send" (insight vs AI) toggle — new parent-anchored subs, feature on. */
    showResourceTypeToggle: boolean
    /** The AI option in the toggle is selectable (vs greyed with a consent reason). */
    aiOptionEnabled: boolean
    /** Insight-flow hint: feature exists but consent is missing. */
    showConsentHint: boolean
    /** AI-only-form banner: feature exists, consent missing, creating (not editing). */
    showAiFormConsentBanner: boolean
    /** Block submit on a new AI subscription that can't be created — mirrors the create-only backend gate. */
    submitBlocked: boolean
}

/**
 * Single source of truth for how the AI-subscription feature flag (visibility) and the
 * org AI-data-processing consent (enablement) gate the subscription form. Pure so the
 * flag-off / consent-missing combinations are provable without rendering the component.
 *
 * - flag off → the feature does not exist: hide the toggle, option, and banners.
 * - flag on, no consent → it exists but is blocked: toggle shows with AI greyed + a consent
 *   hint; submit is blocked on the AI-only form.
 * - editing → never block (the backend gates creation only; users must be able to edit/disable).
 */
export function getAiSubscriptionGate(inputs: AiSubscriptionGateInputs): AiSubscriptionGate {
    const { isAiPrompt, isParentless, isEditing, aiConsentApproved, isCloud, isDebug, aiFlagEnabled } = inputs
    const aiAllowed = aiConsentApproved && (isCloud || isDebug) && aiFlagEnabled
    const showResourceTypeToggle = !isParentless && !isEditing && aiFlagEnabled
    return {
        aiAllowed,
        showResourceTypeToggle,
        aiOptionEnabled: aiAllowed,
        showConsentHint: showResourceTypeToggle && !aiAllowed,
        showAiFormConsentBanner: isAiPrompt && !isEditing && aiFlagEnabled && !aiAllowed,
        submitBlocked: isAiPrompt && !isEditing && !aiAllowed,
    }
}
