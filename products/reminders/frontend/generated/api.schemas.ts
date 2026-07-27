/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `daily` - Daily
 * * `weekly` - Weekly
 * * `monthly` - Monthly
 * * `yearly` - Yearly
 */
export type RecurrenceIntervalEnumApi = (typeof RecurrenceIntervalEnumApi)[keyof typeof RecurrenceIntervalEnumApi]

export const RecurrenceIntervalEnumApi = {
    Daily: 'daily',
    Weekly: 'weekly',
    Monthly: 'monthly',
    Yearly: 'yearly',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * * `active` - Active
 * * `completed` - Completed
 * * `errored` - Errored
 */
export type ReminderStatusEnumApi = (typeof ReminderStatusEnumApi)[keyof typeof ReminderStatusEnumApi]

export const ReminderStatusEnumApi = {
    Active: 'active',
    Completed: 'completed',
    Errored: 'errored',
} as const

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface ReminderApi {
    readonly id: string
    /** ID of the organization this reminder belongs to. You must be a member of it. */
    organization: string
    /**
     * Optional ID of the project this reminder is scoped to. Required when targeting a specific resource. Must belong to the chosen organization.
     * @nullable
     */
    team?: number | null
    /**
     * Short text shown as the notification title when the reminder fires.
     * @maxLength 255
     */
    title: string
    /** Optional longer body for the notification. */
    message?: string
    /**
     * Optional PostHog resource this reminder is about. One of: dashboard, insight, experiment, feature_flag, survey, notebook, replay, error_tracking. Resources are project-scoped, so a team must be set when this is provided.
     * @maxLength 50
     * @nullable
     */
    resource_type?: string | null
    /**
     * ID of the referenced resource; must exist in the chosen project.
     * @maxLength 200
     * @nullable
     */
    resource_id?: string | null
    /**
     * For a one-off reminder: when it should fire (ISO 8601, future).
     * @nullable
     */
    scheduled_at?: string | null
    /** For a recurring reminder: daily, weekly, monthly, or yearly.
     *
     * * `daily` - Daily
     * * `weekly` - Weekly
     * * `monthly` - Monthly
     * * `yearly` - Yearly */
    recurrence_interval?: RecurrenceIntervalEnumApi | BlankEnumApi | null
    /**
     * For a recurring reminder: a 5-field cron expression (e.g. '0 9 * * 1' = Mondays 9am). May fire at most 4 times per day. Mutually exclusive with recurrence_interval.
     * @maxLength 100
     * @nullable
     */
    cron_expression?: string | null
    /**
     * IANA timezone the schedule resolves in (e.g. 'America/New_York'). Defaults to the project timezone when a team is set, otherwise UTC.
     * @maxLength 64
     */
    timezone?: string
    /**
     * Optional: recurring reminders stop (status=completed) after this time.
     * @nullable
     */
    end_date?: string | null
    /** @nullable */
    readonly next_fire_at: string | null
    /** @nullable */
    readonly last_fired_at: string | null
    readonly status: ReminderStatusEnumApi
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedReminderListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ReminderApi[]
}

export interface PatchedReminderApi {
    readonly id?: string
    /** ID of the organization this reminder belongs to. You must be a member of it. */
    organization?: string
    /**
     * Optional ID of the project this reminder is scoped to. Required when targeting a specific resource. Must belong to the chosen organization.
     * @nullable
     */
    team?: number | null
    /**
     * Short text shown as the notification title when the reminder fires.
     * @maxLength 255
     */
    title?: string
    /** Optional longer body for the notification. */
    message?: string
    /**
     * Optional PostHog resource this reminder is about. One of: dashboard, insight, experiment, feature_flag, survey, notebook, replay, error_tracking. Resources are project-scoped, so a team must be set when this is provided.
     * @maxLength 50
     * @nullable
     */
    resource_type?: string | null
    /**
     * ID of the referenced resource; must exist in the chosen project.
     * @maxLength 200
     * @nullable
     */
    resource_id?: string | null
    /**
     * For a one-off reminder: when it should fire (ISO 8601, future).
     * @nullable
     */
    scheduled_at?: string | null
    /** For a recurring reminder: daily, weekly, monthly, or yearly.
     *
     * * `daily` - Daily
     * * `weekly` - Weekly
     * * `monthly` - Monthly
     * * `yearly` - Yearly */
    recurrence_interval?: RecurrenceIntervalEnumApi | BlankEnumApi | null
    /**
     * For a recurring reminder: a 5-field cron expression (e.g. '0 9 * * 1' = Mondays 9am). May fire at most 4 times per day. Mutually exclusive with recurrence_interval.
     * @maxLength 100
     * @nullable
     */
    cron_expression?: string | null
    /**
     * IANA timezone the schedule resolves in (e.g. 'America/New_York'). Defaults to the project timezone when a team is set, otherwise UTC.
     * @maxLength 64
     */
    timezone?: string
    /**
     * Optional: recurring reminders stop (status=completed) after this time.
     * @nullable
     */
    end_date?: string | null
    /** @nullable */
    readonly next_fire_at?: string | null
    /** @nullable */
    readonly last_fired_at?: string | null
    readonly status?: ReminderStatusEnumApi
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
}

export type RemindersListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
