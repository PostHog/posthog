import { SubscriptionFreeTierLimit } from '~/queries/schema/schema-general'
import { IntegrationType, SubscriptionType } from '~/types'

import { SubscriptionTargetEnumApi } from 'products/subscriptions/frontend/generated/api.schemas'

import {
    canNudgeToSubscribe,
    coerceDeliveryConfigForScope,
    formatSubscriptionSchedule,
    getAiSubscriptionDisplayOptionState,
    getAiSubscriptionDisplaySummary,
    getAiSubscriptionGate,
    getNextDeliveryDate,
    getSubscriptionAdvancedSettings,
    integrationHasFilesWrite,
    selectedDaysToDayPickerLabel,
    shouldShowDayPicker,
    targetTypeOptions,
    toggleSelectedDay,
    updateAiSubscriptionDisplayOption,
} from './utils'

describe('targetTypeOptions', () => {
    it('offers every destination the API accepts', () => {
        // A destination the backend accepts but the select never offers is unreachable in the UI.
        expect(targetTypeOptions.map(({ value }) => value)).toEqual(Object.values(SubscriptionTargetEnumApi))
    })
})

describe('day picker values', () => {
    it.each([
        ['daily', 1, true],
        ['daily', 2, false],
        ['weekly', 1, true],
        ['weekly', 2, true],
        ['monthly', 1, false],
        ['yearly', 1, false],
    ] as const)('%s interval %s shows day picker: %s', (frequency, interval, expected) => {
        expect(shouldShowDayPicker(frequency, interval)).toBe(expected)
    })

    it.each([
        [[], 'Select at least one day'],
        [['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], 'on Monday to Sunday'],
        [['monday', 'tuesday', 'wednesday', 'thursday', 'friday'], 'on weekdays'],
        [['saturday', 'sunday'], 'on weekends'],
        [['wednesday'], 'on Wednesday'],
        [['monday', 'wednesday'], 'on 2 days'],
    ] as const)('summarizes %s as %s', (selectedDays, expected) => {
        expect(selectedDaysToDayPickerLabel([...selectedDays])).toBe(expected)
    })

    it.each([
        ['adds another day', ['wednesday'], 'tuesday', ['tuesday', 'wednesday']],
        ['removes a selected day', ['tuesday', 'wednesday'], 'tuesday', ['wednesday']],
    ] as const)('%s without replacing the other selections', (_label, selectedDays, day, expected) => {
        expect(toggleSelectedDay([...selectedDays], day)).toEqual(expected)
    })
})

describe('formatSubscriptionSchedule', () => {
    it('includes every selected delivery day in a weekly schedule summary', () => {
        expect(
            formatSubscriptionSchedule({
                frequency: 'weekly',
                interval: 1,
                start_date: '2024-01-01T09:00:00Z',
                byweekday: ['monday', 'wednesday'],
            })
        ).toBe('Every 1 week on Monday and Wednesday at 9:00 AM')
    })
})

describe('getSubscriptionAdvancedSettings', () => {
    it('lists only delivery settings that differ from the default flow', () => {
        expect(
            getSubscriptionAdvancedSettings({
                summary_enabled: true,
                summary_prompt_guide: 'Prioritize activation changes',
                send_test_now: false,
            })
        ).toEqual(['Automatic AI summary', 'Custom AI summary context', 'No test delivery'])
    })
})

describe('AI subscription display options', () => {
    it.each([
        ['uses full report for legacy subscriptions with no display flags', undefined, 'Full report'],
        [
            'recognizes the report-only state',
            {
                include_images: false,
                include_feedback: false,
                include_manage_link: false,
                include_posthog_hint: false,
            },
            'Report only',
        ],
        [
            'recognizes the report-and-charts state',
            {
                include_images: true,
                include_feedback: false,
                include_manage_link: false,
                include_posthog_hint: false,
            },
            'Report + charts',
        ],
        [
            'names feedback-only content',
            {
                include_images: false,
                include_feedback: true,
                include_manage_link: false,
                include_posthog_hint: false,
            },
            'Report + feedback',
        ],
        [
            'names PostHog-only content',
            {
                include_images: false,
                include_feedback: false,
                include_manage_link: true,
                include_posthog_hint: true,
            },
            'Report + PostHog links and suggestions',
        ],
        [
            'names charts and feedback content',
            {
                include_images: true,
                include_feedback: true,
                include_manage_link: false,
                include_posthog_hint: false,
            },
            'Report + charts + feedback',
        ],
        [
            'names charts and PostHog content',
            {
                include_images: true,
                include_feedback: false,
                include_manage_link: true,
                include_posthog_hint: true,
            },
            'Report + charts + PostHog links and suggestions',
        ],
        [
            'names feedback and PostHog content',
            {
                include_images: false,
                include_feedback: true,
                include_manage_link: true,
                include_posthog_hint: true,
            },
            'Report + feedback + PostHog links and suggestions',
        ],
        [
            'names an API-managed manage-link-only state',
            {
                include_images: false,
                include_feedback: false,
                include_manage_link: true,
                include_posthog_hint: false,
            },
            'Report + manage link',
        ],
        [
            'names an API-managed suggestion-only state',
            {
                include_images: false,
                include_feedback: false,
                include_manage_link: false,
                include_posthog_hint: true,
            },
            'Report + PostHog suggestion',
        ],
    ] as const)('%s', (_label, deliveryConfig, expected) => {
        expect(getAiSubscriptionDisplaySummary(deliveryConfig)).toBe(expected)
    })

    it.each([
        ['images', false, { include_images: false }],
        ['feedback', false, { include_feedback: false }],
        ['posthog_actions', false, { include_manage_link: false, include_posthog_hint: false }],
    ] as const)('updates %s without losing unrelated delivery settings', (option, enabled, expectedDisplayConfig) => {
        expect(
            updateAiSubscriptionDisplayOption(
                {
                    post_all_insights_in_main_message: true,
                    include_images: true,
                    include_feedback: true,
                    include_manage_link: true,
                    include_posthog_hint: true,
                },
                option,
                enabled
            )
        ).toEqual({
            post_all_insights_in_main_message: true,
            include_images: true,
            include_feedback: true,
            include_manage_link: true,
            include_posthog_hint: true,
            ...expectedDisplayConfig,
        })
    })

    it('treats either PostHog action flag as enabled', () => {
        expect(
            getAiSubscriptionDisplayOptionState(
                { include_manage_link: true, include_posthog_hint: false },
                'posthog_actions'
            )
        ).toBe(true)
    })

    it('treats omitted legacy flags as enabled', () => {
        expect(getAiSubscriptionDisplayOptionState(undefined, 'images')).toBe(true)
        expect(getAiSubscriptionDisplayOptionState(undefined, 'feedback')).toBe(true)
        expect(getAiSubscriptionDisplayOptionState(undefined, 'posthog_actions')).toBe(true)
    })

    it.each([
        ['Slack', SubscriptionTargetEnumApi.Slack, 'Full report'],
        ['email', SubscriptionTargetEnumApi.Email, 'Full report'],
        ['Microsoft Teams', SubscriptionTargetEnumApi.Teams, 'Full report'],
    ] as const)('lists the content that %s recipients receive', (_label, targetType, expected) => {
        expect(getAiSubscriptionDisplaySummary(undefined, targetType)).toBe(expected)
    })

    it.each([
        ['the PostHog suggestion', { include_posthog_hint: false }, 'Report + charts + feedback + manage link'],
        ['the manage link', { include_manage_link: false }, 'Report + charts + feedback + PostHog suggestion'],
    ] as const)('does not call a Slack report full when it drops %s', (_label, deliveryConfig, expected) => {
        expect(getAiSubscriptionDisplaySummary(deliveryConfig, SubscriptionTargetEnumApi.Slack)).toBe(expected)
    })

    it.each([
        ['insight', undefined],
        ['dashboard', undefined],
        ['ai_prompt', false],
    ] as const)('a %s subscription sends include_images as %s', (resourceType, expected) => {
        const subscription = {
            resource_type: resourceType,
            target_type: 'email',
            delivery_config: { include_images: false },
        } as SubscriptionType

        expect(coerceDeliveryConfigForScope(subscription, [])?.include_images).toBe(expected)
    })

    it('keeps the other delivery options when it drops the AI ones', () => {
        const subscription = {
            resource_type: 'insight',
            target_type: 'slack',
            integration_id: 7,
            delivery_config: { post_all_insights_in_main_message: true, include_feedback: true },
        } as SubscriptionType

        expect(
            coerceDeliveryConfigForScope(subscription, [
                { id: 7, kind: 'slack', config: { scope: 'files:write' } } as IntegrationType,
            ])
        ).toEqual({ post_all_insights_in_main_message: true })
    })
})

describe('Slack gallery delivery config', () => {
    const slackIntegration = (id: number, scope: string): IntegrationType =>
        ({ id, kind: 'slack', config: { scope } }) as IntegrationType
    const subscription = (args: Partial<SubscriptionType>): SubscriptionType =>
        ({
            target_type: 'slack',
            integration_id: 7,
            delivery_config: { post_all_insights_in_main_message: true },
            ...args,
        }) as SubscriptionType

    it.each([
        ['granted', slackIntegration(7, 'chat:write,files:write,channels:read'), true],
        ['missing', slackIntegration(7, 'chat:write,channels:read'), false],
        ['substring only', slackIntegration(7, 'files:write:advanced'), false],
        ['missing integration', undefined, false],
    ] as const)('detects files:write when it is %s', (_label, integration, expected) => {
        expect(integrationHasFilesWrite(integration)).toBe(expected)
    })

    it.each<[string, SubscriptionType, IntegrationType[] | null | undefined, boolean]>([
        ['removes the flag when files:write is missing', subscription({}), [slackIntegration(7, 'chat:write')], false],
        ['keeps the flag when files:write is granted', subscription({}), [slackIntegration(7, 'files:write')], true],
        [
            'removes the flag for a non-Slack target',
            subscription({ target_type: 'email' }),
            [slackIntegration(7, 'files:write')],
            false,
        ],
        [
            'removes the flag for a prompt subscription',
            subscription({ resource_type: 'ai_prompt' }),
            [slackIntegration(7, 'files:write')],
            false,
        ],
        ['removes the flag when the loaded integration is missing', subscription({}), [], false],
        ['preserves the flag while integrations are unresolved', subscription({}), null, true],
    ])('%s', (_label, value, integrations, expected) => {
        expect(coerceDeliveryConfigForScope(value, integrations)?.post_all_insights_in_main_message).toBe(expected)
    })

    it('returns an already-disabled config unchanged', () => {
        const config = { post_all_insights_in_main_message: false }
        const value = subscription({ delivery_config: config })
        expect(coerceDeliveryConfigForScope(value, [])).toBe(config)
    })
})

describe('getNextDeliveryDate', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-01-15T12:00:00Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['frequency is missing', { start_date: '2024-01-01T09:00:00Z' }],
        ['start_date is missing', { frequency: 'daily' }],
        ['subscription is empty', {}],
    ] as const)('returns null when %s', (_label, subscription) => {
        expect(getNextDeliveryDate(subscription)).toBeNull()
    })

    it.each([
        ['with explicit interval', { frequency: 'daily', interval: 1, start_date: '2024-01-01T09:00:00Z' }],
        ['defaulting interval to 1', { frequency: 'daily', start_date: '2024-01-01T09:00:00Z' }],
    ] as const)('computes next daily delivery %s', (_label, subscription) => {
        expect(getNextDeliveryDate(subscription)).toEqual(new Date('2024-01-16T09:00:00Z'))
    })

    it('computes the next selected daily delivery day', () => {
        const result = getNextDeliveryDate({
            frequency: 'daily',
            interval: 1,
            start_date: '2024-01-01T09:00:00Z',
            byweekday: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
        })
        expect(result).toEqual(new Date('2024-01-16T09:00:00Z'))
    })

    it('computes the next selected weekly delivery day', () => {
        const result = getNextDeliveryDate({
            frequency: 'weekly',
            interval: 1,
            start_date: '2024-01-01T09:00:00Z',
            byweekday: ['wednesday', 'friday'],
        })
        expect(result).toEqual(new Date('2024-01-17T09:00:00Z'))
    })

    it('computes next monthly delivery with bysetpos', () => {
        const result = getNextDeliveryDate({
            frequency: 'monthly',
            interval: 1,
            start_date: '2024-01-01T09:00:00Z',
            byweekday: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
            bysetpos: 1,
        })
        // First weekday of Feb 2024 is Thu Feb 1
        expect(result).toEqual(new Date('2024-02-01T09:00:00Z'))
    })

    it('returns null on invalid rrule config', () => {
        const result = getNextDeliveryDate({
            frequency: 'invalid_freq' as any,
            start_date: '2024-01-01T09:00:00Z',
        })
        expect(result).toBeNull()
    })

    it('keeps the local wall time across a DST transition', () => {
        // Weekly Monday 8am US/Central created in summer (stored 13:00 UTC). After the
        // Nov 1 transition to CST the delivery must stay at 8am local = 14:00 UTC.
        jest.setSystemTime(new Date('2026-11-10T12:00:00Z'))
        const result = getNextDeliveryDate(
            {
                frequency: 'weekly',
                interval: 1,
                start_date: '2026-06-01T13:00:00Z',
                byweekday: ['monday'],
            },
            'US/Central'
        )
        expect(result).toEqual(new Date('2026-11-16T14:00:00Z'))
    })

    it('keeps the local wall time across spring forward', () => {
        // 8am US/Central in winter (14:00 UTC) becomes 13:00 UTC after the Mar 2027 transition.
        jest.setSystemTime(new Date('2027-03-15T00:00:00Z'))
        const result = getNextDeliveryDate(
            {
                frequency: 'weekly',
                interval: 1,
                start_date: '2027-01-04T14:00:00Z',
                byweekday: ['monday'],
            },
            'US/Central'
        )
        expect(result).toEqual(new Date('2027-03-15T13:00:00Z'))
    })

    it('keeps the fixed UTC behavior when no timezone is given', () => {
        jest.setSystemTime(new Date('2026-11-10T12:00:00Z'))
        const result = getNextDeliveryDate({
            frequency: 'weekly',
            interval: 1,
            start_date: '2026-06-01T13:00:00Z',
            byweekday: ['monday'],
        })
        expect(result).toEqual(new Date('2026-11-16T13:00:00Z'))
    })

    it('handles half-hour offset timezones without DST', () => {
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2024-01-01T03:30:00Z' },
            'Asia/Kolkata'
        )
        expect(result).toEqual(new Date('2024-01-16T03:30:00Z'))
    })

    it('resolves an ambiguous wall time to the earlier (pre-transition) occurrence', () => {
        // Daily 1:30am US/Central: on Nov 1 2026 the wall time happens twice (CDT, then CST).
        // Both backend (zoneinfo fold=0) and this mirror pick the earlier occurrence,
        // 1:30am CDT = 06:30 UTC.
        jest.setSystemTime(new Date('2026-10-31T12:00:00Z'))
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-10-20T06:30:00Z' },
            'US/Central'
        )
        expect(result).toEqual(new Date('2026-11-01T06:30:00Z'))
    })

    it('returns the first fold occurrence while it is still ahead', () => {
        // Daily 1:30am US/Central, computed at 1:15am CDT (06:15 UTC) on transition day.
        jest.setSystemTime(new Date('2026-11-01T06:15:00Z'))
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-10-20T06:30:00Z' },
            'US/Central'
        )
        expect(result).toEqual(new Date('2026-11-01T06:30:00Z'))
    })

    it('returns the second fold occurrence once the first is past', () => {
        // Same schedule computed during the repeated hour, at 1:15am CST (07:15 UTC):
        // the first 1:30am (06:30 UTC) is already past, so the delivery is the second
        // occurrence of that wall time: 1:30am CST = 07:30 UTC.
        jest.setSystemTime(new Date('2026-11-01T07:15:00Z'))
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-10-20T06:30:00Z' },
            'US/Central'
        )
        expect(result).toEqual(new Date('2026-11-01T07:30:00Z'))
    })

    it('returns the second fold when the first-fold wall time has already passed', () => {
        // Daily 1:30am US/Central at 1:45am CDT (06:45 UTC): the 1:30 wall time is behind on
        // the wall clock, but its second occurrence (1:30am CST = 07:30 UTC) is still ahead.
        jest.setSystemTime(new Date('2026-11-01T06:45:00Z'))
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-10-20T06:30:00Z' },
            'US/Central'
        )
        expect(result).toEqual(new Date('2026-11-01T07:30:00Z'))
    })

    it('treats the current instant as already past at an exact occurrence', () => {
        // Exactly at the first-fold 1:30am (06:30 UTC): strictly-after semantics move to the
        // second occurrence at 1:30am CST (07:30 UTC).
        jest.setSystemTime(new Date('2026-11-01T06:30:00Z'))
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-10-20T06:30:00Z' },
            'US/Central'
        )
        expect(result).toEqual(new Date('2026-11-01T07:30:00Z'))
    })

    it('handles half-hour backward transitions', () => {
        // Australia/Lord_Howe falls back 30 minutes on Apr 4 2027: daily 1:45am exists at
        // 14:45 UTC (+11) and 15:15 UTC (+10:30). At 14:50 UTC only the second is ahead.
        jest.setSystemTime(new Date('2027-04-03T14:50:00Z'))
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2027-03-20T14:45:00Z' },
            'Australia/Lord_Howe'
        )
        expect(result).toEqual(new Date('2027-04-03T15:15:00Z'))
    })

    it('normalizes a nonexistent wall time forward', () => {
        // Daily 2:30am US/Central: on Mar 14 2027 that wall time never happens (spring
        // forward 02:00 -> 03:00). The recurrence normalizes forward to the next valid
        // instant: 2:30am in the pre-transition offset = 08:30 UTC = 3:30am CDT.
        jest.setSystemTime(new Date('2027-03-13T12:00:00Z'))
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2027-03-01T08:30:00Z' },
            'US/Central'
        )
        expect(result).toEqual(new Date('2027-03-14T08:30:00Z'))
    })

    it('keeps an early wall time across a positive-offset spring transition', () => {
        // Daily 1:00am Australia/Sydney: on the Oct 4 2026 spring-forward day (02:00 ->
        // 03:00) 1:00am still exists, ahead of the gap, so the delivery is 15:00 UTC
        // Oct 3 with the pre-transition offset. The next day moves to 14:00 UTC (+11).
        // Parity with Subscription._compute_next_delivery_date.
        jest.setSystemTime(new Date('2026-10-03T12:00:00Z'))
        const onTransitionDay = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-09-01T15:00:00Z' },
            'Australia/Sydney'
        )
        expect(onTransitionDay).toEqual(new Date('2026-10-03T15:00:00Z'))

        jest.setSystemTime(new Date('2026-10-04T12:00:00Z'))
        const after = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-09-01T15:00:00Z' },
            'Australia/Sydney'
        )
        expect(after).toEqual(new Date('2026-10-04T14:00:00Z'))
    })

    it('keeps an early wall time across a half-hour spring forward', () => {
        // Daily 12:15am Australia/Lord_Howe: the Oct 4 2026 spring forward (02:00 ->
        // 02:30) leaves 12:15am intact at 13:45 UTC (+10:30); the next day is 13:15 UTC.
        jest.setSystemTime(new Date('2026-10-03T12:00:00Z'))
        const onTransitionDay = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-09-01T13:45:00Z' },
            'Australia/Lord_Howe'
        )
        expect(onTransitionDay).toEqual(new Date('2026-10-03T13:45:00Z'))

        jest.setSystemTime(new Date('2026-10-04T12:00:00Z'))
        const after = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-09-01T13:45:00Z' },
            'Australia/Lord_Howe'
        )
        expect(after).toEqual(new Date('2026-10-04T13:15:00Z'))
    })

    it('returns both occurrences of a two-hour fold', () => {
        // Antarctica/Troll falls back two hours on Oct 25 2026 (03:00 -> 01:00), so daily
        // 2:00am exists at 00:00 UTC (+2) and again at 02:00 UTC (+0).
        jest.setSystemTime(new Date('2026-10-24T23:00:00Z'))
        const before = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-10-20T00:00:00Z' },
            'Antarctica/Troll'
        )
        expect(before).toEqual(new Date('2026-10-25T00:00:00Z'))

        jest.setSystemTime(new Date('2026-10-25T00:30:00Z'))
        const between = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-10-20T00:00:00Z' },
            'Antarctica/Troll'
        )
        expect(between).toEqual(new Date('2026-10-25T02:00:00Z'))

        jest.setSystemTime(new Date('2026-10-25T02:30:00Z'))
        const after = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-10-20T00:00:00Z' },
            'Antarctica/Troll'
        )
        expect(after).toEqual(new Date('2026-10-26T02:00:00Z'))
    })

    it('normalizes a nonexistent wall time across a positive-offset gap', () => {
        // Daily 2:30am Australia/Sydney does not exist on Oct 4 2026 (02:00 -> 03:00):
        // deliver at the pre-transition offset, 16:30 UTC Oct 3, matching the backend.
        jest.setSystemTime(new Date('2026-10-03T12:00:00Z'))
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '2026-09-01T16:30:00Z' },
            'Australia/Sydney'
        )
        expect(result).toEqual(new Date('2026-10-03T16:30:00Z'))
    })

    it('matches the backend at sub-second boundaries', () => {
        // dateutil's rrule works at whole-second precision and the preview mirrors it: a
        // 9:00:00.500 start produces 9:00:00 occurrences on both stacks, and an occurrence
        // is only next while it is strictly ahead.
        const subscription = { frequency: 'daily', interval: 1, start_date: '2026-09-01T13:00:00.500Z' }

        jest.setSystemTime(new Date('2026-10-15T12:59:59.950Z'))
        expect(getNextDeliveryDate(subscription, 'America/New_York')).toEqual(new Date('2026-10-15T13:00:00Z'))

        jest.setSystemTime(new Date('2026-10-15T13:00:00.000Z'))
        expect(getNextDeliveryDate(subscription, 'America/New_York')).toEqual(new Date('2026-10-16T13:00:00Z'))

        jest.setSystemTime(new Date('2026-10-15T13:00:00.050Z'))
        expect(getNextDeliveryDate(subscription, 'America/New_York')).toEqual(new Date('2026-10-16T13:00:00Z'))
    })

    it('handles second-precision historical offset transitions', () => {
        // America/Argentina/Catamarca sprang forward 16m48s on May 1 1920 (00:00 ->
        // 00:16:48): daily 00:01:20 never happens that day and delivers at the
        // pre-transition offset, matching Subscription._compute_next_delivery_date.
        jest.setSystemTime(new Date('1920-04-30T12:00:00Z'))
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '1920-04-29T04:18:08Z' },
            'America/Argentina/Catamarca'
        )
        expect(result).toEqual(new Date('1920-05-01T04:18:08Z'))
    })

    it('handles sub-minute historical gaps', () => {
        // America/Bahia_Banderas sprang forward 60 seconds on Jan 1 1922 (23:59 -> 00:00):
        // daily 23:59:30 never happens, delivering at the pre-transition offset.
        jest.setSystemTime(new Date('1921-12-31T12:00:00Z'))
        const result = getNextDeliveryDate(
            { frequency: 'daily', interval: 1, start_date: '1921-12-30T07:00:30Z' },
            'America/Bahia_Banderas'
        )
        expect(result).toEqual(new Date('1922-01-01T07:00:30Z'))
    })
})

describe('getAiSubscriptionGate', () => {
    // Fully-enabled baseline (insight flow, new sub, consent + cloud + flag all on); each case overrides.
    const base = {
        isAiPrompt: false,
        isParentless: false,
        isEditing: false,
        aiConsentApproved: true,
        isCloud: true,
        isDebug: false,
        aiFlagEnabled: true,
    } as const

    it.each([
        [
            'flag off hides every AI affordance',
            { aiFlagEnabled: false },
            { aiAllowed: false, showResourceTypeToggle: false, showConsentHint: false, showAiFormConsentBanner: false },
        ],
        [
            'flag on + consent + cloud fully enables AI',
            {},
            {
                aiAllowed: true,
                showResourceTypeToggle: true,
                aiOptionEnabled: true,
                showConsentHint: false,
                submitBlocked: false,
            },
        ],
        [
            'flag on + no consent greys AI and shows the consent hint (insight flow)',
            { aiConsentApproved: false },
            { aiAllowed: false, showResourceTypeToggle: true, aiOptionEnabled: false, showConsentHint: true },
        ],
        [
            'top-level AI form blocks submit and shows the banner when consent is missing',
            { isParentless: true, isAiPrompt: true, aiConsentApproved: false },
            { showResourceTypeToggle: false, showAiFormConsentBanner: true, submitBlocked: true },
        ],
        [
            'editing an AI sub never blocks, even without consent',
            { isEditing: true, isAiPrompt: true, aiConsentApproved: false },
            { showAiFormConsentBanner: false, submitBlocked: false, showResourceTypeToggle: false },
        ],
        ['debug mode satisfies the cloud requirement locally', { isCloud: false, isDebug: true }, { aiAllowed: true }],
        [
            'flag off shows no misleading consent banner on the AI-only form (but still blocks submit)',
            { isParentless: true, isAiPrompt: true, aiFlagEnabled: false, aiConsentApproved: false },
            { showAiFormConsentBanner: false, submitBlocked: true },
        ],
    ] as const)('%s', (_label, overrides, expected) => {
        expect(getAiSubscriptionGate({ ...base, ...overrides })).toMatchObject(expected)
    })
})

describe('canNudgeToSubscribe', () => {
    // isFreeTierCreateAtLimit fails open on an unknown count so the form still renders. The nudge
    // wants the opposite, so the null case is decided here rather than left to that helper.
    it.each([
        ['a paid plan is nudged whatever the free-tier count says', true, null, true],
        ['free tier with room left is nudged', false, 0, true],
        ['free tier at the limit is not nudged', false, SubscriptionFreeTierLimit.COUNT, false],
        ['an unknown count is not nudged', false, null, false],
    ] as const)('%s', (_label, hasSubscriptionsFeature, freeTierSubscriptionCount, expected) => {
        expect(canNudgeToSubscribe(hasSubscriptionsFeature, freeTierSubscriptionCount)).toBe(expected)
    })
})
