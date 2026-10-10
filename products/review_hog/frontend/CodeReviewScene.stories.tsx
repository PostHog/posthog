import {
    MOCK_DEFAULT_BASIC_USER,
    MOCK_DEFAULT_ORGANIZATION_MEMBER,
    MOCK_DEFAULT_USER,
    MOCK_SECOND_BASIC_USER,
} from 'lib/api.mock'

import { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'
import { OrganizationMemberType, UserBasicType } from '~/types'

import type {
    AutomaticFlashForEnumApi,
    AutomaticReviewDecisionApi,
    AutomaticReviewReasonEnumApi,
    PatchedReviewProjectSettingsApi,
    PatchedReviewUserSettingsApi,
    ReviewInstallationClaimScopeEnumApi,
    ReviewPerspectiveConfigApi,
    ReviewPerspectiveStatsApi,
    ReviewProjectSettingsApi,
    ReviewRecentReviewApi,
    ReviewRepositoryChoiceWriteApi,
    ReviewRepositoryOverviewEntryApi,
    ReviewRepositoryPersonApi,
    ReviewRepositoryPersonRequestApi,
    ReviewRepositoryWriteApi,
    ReviewUserSettingsApi,
    ReviewValidatorConfigApi,
    UserBasicApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { expect } from 'storybook/test'

import { CodeReviewScene } from './CodeReviewScene'
import { CodeReviewTab } from './reviewHogSettingsLogic'

const defaultSettings: ReviewUserSettingsApi = {
    default_review_mode: 'follow',
    resolve_comments: false,
    urgency_threshold: 'consider',
    celebrate_clean_reviews: true,
    review_inbox_prs: false,
    stamphog_review_inbox_prs: false,
    sources: {
        default_review_mode: 'default',
        resolve_comments: 'default',
        urgency_threshold: 'default',
        celebrate_clean_reviews: 'default',
        review_inbox_prs: 'default',
        stamphog_review_inbox_prs: 'default',
    },
    project_defaults: { urgency_threshold: 'consider', celebrate_clean_reviews: true },
    stamphog_connected: false,
}

function completedReview(overrides: Partial<ReviewRecentReviewApi>): ReviewRecentReviewApi {
    return {
        id: 'review-1',
        repository: 'example-org/example-repo',
        pr_number: 101,
        pr_title: 'Add retry to the export job',
        pr_author: 'example-dev',
        additions: 120,
        deletions: 34,
        changed_files: 6,
        head_branch: 'feat/export-retry',
        github_url: 'https://github.com/example-org/example-repo/pull/101',
        run_count: 1,
        last_run_at: '2026-09-30T10:00:00Z',
        published: true,
        full_review_published: true,
        in_progress: false,
        progress: null,
        resolution: null,
        must_fix_count: 1,
        should_fix_count: 2,
        consider_count: 1,
        candidate_count: 7,
        dismissed_count: 3,
        files_reviewed: 6,
        chunk_count: 2,
        perspective_count: 3,
        perspective_issue_count: 8,
        blind_spot_issue_count: 2,
        ...overrides,
    }
}

const recentReviews: ReviewRecentReviewApi[] = [
    completedReview({}),
    completedReview({
        id: 'review-2',
        pr_number: 98,
        pr_title: 'Fix timezone handling in the weekly digest',
        github_url: 'https://github.com/example-org/example-repo/pull/98',
        head_branch: 'fix/digest-timezone',
        last_run_at: '2026-09-29T15:30:00Z',
        must_fix_count: 0,
        should_fix_count: 1,
        consider_count: 0,
        dismissed_count: 1,
    }),
    // Started by the viewer on a teammate's pull request, so "Mine" shows its author.
    completedReview({
        id: 'review-3',
        pr_number: 95,
        pr_title: 'Cache the billing summary',
        pr_author: 'example-teammate',
        github_url: 'https://github.com/example-org/example-repo/pull/95',
        head_branch: 'feat/billing-cache',
        last_run_at: '2026-09-28T09:00:00Z',
        must_fix_count: 0,
        should_fix_count: 0,
        consider_count: 1,
        dismissed_count: 2,
    }),
]

const perspectiveStats: ReviewPerspectiveStatsApi = {
    report_count: 2,
    perspectives: [
        { skill_name: 'review-hog-perspective-logic-correctness', raised: 6, kept: 4, dismissed: 2 },
        { skill_name: 'review-hog-perspective-performance-reliability', raised: 3, kept: 1, dismissed: 2 },
        { skill_name: 'review-hog-blind-spots-general', raised: 2, kept: 1, dismissed: 1 },
    ],
}

const perspectives: ReviewPerspectiveConfigApi[] = [
    {
        skill_name: 'review-hog-perspective-logic-correctness',
        enabled: true,
        description: 'Wrong results, broken edge cases, missed branches.',
        body: '',
    },
    {
        skill_name: 'review-hog-perspective-performance-reliability',
        enabled: true,
        description: 'Slow queries, retries, timeouts, unbounded work.',
        body: '',
    },
    {
        skill_name: 'review-hog-perspective-contracts-security',
        enabled: false,
        description: 'Tenant leaks, injection, secrets, auth gaps.',
        body: '',
    },
]

function singleSkill(skill_name: string, description: string, active: boolean): ReviewValidatorConfigApi {
    return { skill_name, description, active, body: '' }
}

const ADA: UserBasicType = {
    id: 301,
    uuid: '0b3f6a52-6a0e-4b8e-9d2f-4a1c7e9e0301',
    distinct_id: 'mock-user-301-distinct-id',
    first_name: 'Ada',
    last_name: 'Example',
    email: 'ada@example.com',
}

const members: OrganizationMemberType[] = [
    MOCK_DEFAULT_ORGANIZATION_MEMBER,
    { ...MOCK_DEFAULT_ORGANIZATION_MEMBER, id: 'member-rose', user: MOCK_SECOND_BASIC_USER },
    { ...MOCK_DEFAULT_ORGANIZATION_MEMBER, id: 'member-ada', user: ADA },
]

function toApiUser(user: UserBasicType): UserBasicApi {
    return {
        id: user.id,
        uuid: user.uuid,
        distinct_id: user.distinct_id,
        first_name: user.first_name,
        last_name: user.last_name,
        email: user.email,
        hedgehog_config: null,
    }
}

const INSTALLATION_ID = '4100'

const NAMED_REPOSITORIES = [
    'web',
    'api',
    'docs',
    'billing',
    'mobile-app',
    'infra',
    'sdk-js',
    'sdk-python',
    'design-system',
    'data-pipeline',
]

// Enough repositories for a second page, like a GitHub organization with many services.
const REPOSITORY_NAMES = [
    ...NAMED_REPOSITORIES.map((name) => `example-org/${name}`),
    ...Array.from({ length: 32 }, (_, i) => `example-org/service-${String(i + 1).padStart(3, '0')}`),
]

const BILLING_PROJECT = { id: 2, name: 'Billing' }

interface StoryRepositoryRow {
    id: string
    selected: boolean
    flash_for: AutomaticFlashForEnumApi | null
    people: ReviewRepositoryPersonApi[]
}

/** Mutable API state, reset before each story, so clicks in the panes behave like a real backend. */
const storyState: {
    settings: ReviewUserSettingsApi
    project: ReviewProjectSettingsApi
    rows: Record<string, StoryRepositoryRow>
    choices: Record<string, { id: string; mode: 'flash' | 'off' }>
    nextId: number
} = {
    settings: defaultSettings,
    project: projectSettings('all', true),
    rows: {},
    choices: {},
    nextId: 1,
}

function person(user: UserBasicType, kind: ReviewRepositoryPersonApi['kind']): ReviewRepositoryPersonApi {
    return { id: `person-${user.id}-${kind}`, user: toApiUser(user), kind }
}

function projectSettings(scope: ReviewInstallationClaimScopeEnumApi, canEdit: boolean): ReviewProjectSettingsApi {
    return {
        flash_for: 'everyone',
        bot_prs: 'skip',
        urgency_threshold: 'consider',
        celebrate_clean_reviews: true,
        people: [person(MOCK_SECOND_BASIC_USER, 'excepted')],
        installations: [
            {
                installation_id: INSTALLATION_ID,
                account_name: 'example-org',
                connected_by: toApiUser(ADA),
                claim_id: 'claim-1',
                scope,
                all_taken_by_project: null,
            },
        ],
        can_edit: canEdit,
    }
}

function initialRows(): Record<string, StoryRepositoryRow> {
    return {
        'example-org/web': {
            id: 'repo-web',
            selected: true,
            flash_for: 'everyone',
            people: [person(MOCK_SECOND_BASIC_USER, 'excepted'), person(MOCK_DEFAULT_BASIC_USER, 'excepted')],
        },
        'example-org/api': {
            id: 'repo-api',
            selected: true,
            flash_for: 'listed',
            people: [person(MOCK_SECOND_BASIC_USER, 'listed'), person(ADA, 'listed')],
        },
        'example-org/docs': { id: 'repo-docs', selected: true, flash_for: null, people: [] },
    }
}

function inProject(name: string): boolean {
    if (name === 'example-org/billing') {
        return false
    }
    return storyState.project.installations[0].scope === 'all' || !!storyState.rows[name]?.selected
}

/** A story-sized copy of the backend resolver, so the panes answer like the real API after each change. */
function inherited(name: string, { withDefault = true }: { withDefault?: boolean } = {}): AutomaticReviewDecisionApi {
    if (!inProject(name)) {
        return { flash: false, reason: 'not_in_project' }
    }
    const defaultMode = storyState.settings.default_review_mode ?? 'follow'
    if (withDefault && defaultMode !== 'follow') {
        return { flash: defaultMode === 'flash', reason: 'own_default' }
    }
    const row = storyState.rows[name]
    const exception = row?.flash_for ?? null
    const flashFor = exception ?? storyState.project.flash_for ?? 'off'
    const people = exception ? row.people : storyState.project.people
    const scope = exception ? 'repository' : 'project'
    const listed = (kind: string): boolean =>
        people.some((entry) => entry.kind === kind && entry.user.id === MOCK_DEFAULT_BASIC_USER.id)
    const decision = (flash: boolean, rule: string): AutomaticReviewDecisionApi => ({
        flash,
        reason: `${scope}_${rule}` as AutomaticReviewReasonEnumApi,
    })
    if (flashFor === 'everyone') {
        return listed('excepted') ? decision(false, 'excepted') : decision(true, 'everyone')
    }
    if (flashFor === 'listed') {
        return listed('listed') ? decision(true, 'listed') : decision(false, 'not_listed')
    }
    return decision(false, 'opt_in')
}

function overviewEntry(name: string): ReviewRepositoryOverviewEntryApi {
    const row = storyState.rows[name]
    const choice = storyState.choices[name] ?? null
    const own = inProject(name)
    const base = inherited(name)
    return {
        full_name: name,
        github_repo_id: REPOSITORY_NAMES.indexOf(name) + 1000,
        owner: name === 'example-org/billing' ? 'other_project' : own ? 'this_project' : 'none',
        owner_project: name === 'example-org/billing' ? BILLING_PROJECT : null,
        in_project: own,
        selected: row?.selected ?? false,
        repository_id: row?.id ?? null,
        exception: own && row?.flash_for ? { flash_for: row.flash_for, people: row.people } : null,
        my_choice: own ? (choice?.mode ?? null) : null,
        my_choice_id: own ? (choice?.id ?? null) : null,
        my_result: own && choice ? { flash: choice.mode === 'flash', reason: 'own_repository_choice' } : base,
        inherited_result: base,
        repository_result: inherited(name, { withDefault: false }),
    }
}

function choicesUnlikeDefault(): number {
    const defaultMode = storyState.settings.default_review_mode ?? 'follow'
    return Object.values(storyState.choices).filter((choice) => defaultMode === 'follow' || choice.mode !== defaultMode)
        .length
}

function saveRepository(write: ReviewRepositoryWriteApi): void {
    const current = storyState.rows[write.full_name] ?? {
        id: `repo-new-${storyState.nextId++}`,
        selected: false,
        flash_for: null,
        people: [],
    }
    const next = {
        ...current,
        selected: write.selected ?? current.selected,
        flash_for: write.flash_for !== undefined ? write.flash_for : current.flash_for,
    }
    if (!next.selected && next.flash_for === null) {
        delete storyState.rows[write.full_name]
        return
    }
    storyState.rows[write.full_name] = next
}

function rowById(id: string): [string, StoryRepositoryRow] | undefined {
    return Object.entries(storyState.rows).find(([, row]) => row.id === id)
}

function OpenTab({ tab, children }: { tab: CodeReviewTab; children: JSX.Element }): JSX.Element {
    useEffect(() => {
        router.actions.replace(urls.codeReview(), tab === 'settings' ? { tab } : {})
    }, [tab])
    return children
}

const meta: Meta<typeof CodeReviewScene> = {
    component: CodeReviewScene,
    title: 'Scenes/Code review',
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.REVIEW_HOG],
        mockDate: '2026-10-01T12:00:00Z',
    },
    beforeEach: ({ parameters }) => {
        storyState.settings = {
            ...defaultSettings,
            ...parameters.savedSettings,
        }
        storyState.project = projectSettings(parameters.claimScope ?? 'all', parameters.canEdit ?? true)
        storyState.rows = initialRows()
        storyState.choices = { 'example-org/docs': { id: 'choice-docs', mode: 'off' } }
        storyState.nextId = 1
    },
    decorators: [
        (Story, context): JSX.Element => (
            <OpenTab tab={context.parameters.tab ?? 'activity'}>
                <div className="p-4">
                    <Story />
                </div>
            </OpenTab>
        ),
        (Story, context): JSX.Element => {
            return mswDecorator({
                get: {
                    '/api/users/@me/': () => [
                        200,
                        { ...MOCK_DEFAULT_USER, is_staff: context.parameters.isStaff ?? false },
                    ],
                    '/api/users/@me/github_login/': { github_login: 'example-dev' },
                    '/api/projects/:team_id/review_hog/settings/': () => [200, storyState.settings],
                    '/api/projects/:team_id/review_hog/project_settings/': () => [200, storyState.project],
                    '/api/projects/:team_id/review_hog/repositories/': () => [
                        200,
                        Object.entries(storyState.rows).map(([full_name, row]) => ({
                            ...row,
                            installation_id: INSTALLATION_ID,
                            github_repo_id: null,
                            full_name,
                            created_by: toApiUser(MOCK_DEFAULT_BASIC_USER),
                            created_at: '2026-09-20T10:00:00Z',
                        })),
                    ],
                    '/api/projects/:team_id/review_hog/repository_overview/': ({ request }) => {
                        const params = new URL(request.url).searchParams
                        const search = params.get('search')?.toLowerCase() ?? ''
                        const view = params.get('view') ?? 'all'
                        const offset = Number(params.get('offset') ?? 0)
                        const limit = Number(params.get('limit') ?? 50)
                        const entries = REPOSITORY_NAMES.filter((name) => name.includes(search))
                            .map(overviewEntry)
                            .filter(
                                (entry) =>
                                    view === 'all' ||
                                    (view === 'in_project' && entry.in_project) ||
                                    (view === 'exceptions' && entry.exception !== null) ||
                                    (view === 'mine' && entry.my_choice !== null)
                            )
                        const page = entries.slice(offset, offset + limit)
                        return [
                            200,
                            {
                                installation_id: INSTALLATION_ID,
                                claim_scope: storyState.project.installations[0].scope,
                                results: page,
                                total: entries.length,
                                has_more: offset + limit < entries.length,
                                next_offset: offset + limit < entries.length ? offset + limit : null,
                                my_choices_unlike_default: choicesUnlikeDefault(),
                            },
                        ]
                    },
                    '/api/organizations/:organization_id/members/': {
                        results: members,
                        next: null,
                        previous: null,
                        count: members.length,
                    },
                    '/api/projects/:team_id/review_hog/reviews/': { results: recentReviews, has_more: false },
                    '/api/projects/:team_id/review_hog/reviews/perspective_stats/': perspectiveStats,
                    '/api/projects/:team_id/review_hog/perspectives/': perspectives,
                    '/api/projects/:team_id/review_hog/blind_spots/': [
                        singleSkill(
                            'review-hog-blind-spots-general',
                            'One more pass over each chunk for what every perspective missed.',
                            true
                        ),
                    ],
                    '/api/projects/:team_id/review_hog/validators/': [
                        singleSkill(
                            'review-hog-validation-default',
                            'Drops speculative, noisy and low-value findings before they reach the PR.',
                            true
                        ),
                    ],
                    '/api/projects/:team_id/review_hog/resolution/': [
                        singleSkill(
                            'review-hog-resolution-default',
                            'Fixes what is worth it and safe, and replies to every thread.',
                            true
                        ),
                        singleSkill(
                            'review-hog-resolution-small-fixes',
                            'Fixes only small, local changes and leaves bigger ones as replies.',
                            false
                        ),
                    ],
                },
                post: {
                    '/api/projects/:team_id/review_hog/repositories/': async ({ request }) => {
                        const write = (await request.json()) as ReviewRepositoryWriteApi
                        saveRepository(write)
                        const row = storyState.rows[write.full_name]
                        return [
                            200,
                            {
                                repository: row
                                    ? {
                                          ...row,
                                          installation_id: INSTALLATION_ID,
                                          github_repo_id: null,
                                          full_name: write.full_name,
                                          created_by: null,
                                          created_at: '2026-10-01T12:00:00Z',
                                      }
                                    : null,
                                taken_from_project: null,
                            },
                        ]
                    },
                    '/api/projects/:team_id/review_hog/repositories/:id/people/': async ({ request, params }) => {
                        const { user_id, kind } = (await request.json()) as ReviewRepositoryPersonRequestApi
                        const member = members.find((m) => m.user.id === user_id)
                        const found = rowById(String(params.id))
                        if (!member || !found) {
                            return [400, { error: 'This user is not an active member of the organization.' }]
                        }
                        found[1].people = [...found[1].people, person(member.user, kind)]
                        return [201, {}]
                    },
                    '/api/projects/:team_id/review_hog/project_settings/people/': async ({ request }) => {
                        const { user_id, kind } = (await request.json()) as ReviewRepositoryPersonRequestApi
                        const member = members.find((m) => m.user.id === user_id)
                        if (member) {
                            storyState.project = {
                                ...storyState.project,
                                people: [...storyState.project.people, person(member.user, kind)],
                            }
                        }
                        return [201, storyState.project]
                    },
                    '/api/projects/:team_id/review_hog/repository_choices/': async ({ request }) => {
                        const write = (await request.json()) as ReviewRepositoryChoiceWriteApi
                        if ((write.mode === 'flash') === inherited(write.full_name).flash) {
                            delete storyState.choices[write.full_name]
                        } else {
                            storyState.choices[write.full_name] = {
                                id: `choice-${storyState.nextId++}`,
                                mode: write.mode,
                            }
                        }
                        return [200, { choice: null, my_result: overviewEntry(write.full_name).my_result }]
                    },
                },
                patch: {
                    '/api/projects/:team_id/review_hog/settings/': async ({ request }) => {
                        const update = (await request.json()) as PatchedReviewUserSettingsApi
                        storyState.settings = { ...storyState.settings, ...update }
                        return [200, storyState.settings]
                    },
                    '/api/projects/:team_id/review_hog/project_settings/': async ({ request }) => {
                        const update = (await request.json()) as PatchedReviewProjectSettingsApi
                        storyState.project = { ...storyState.project, ...update }
                        return [200, storyState.project]
                    },
                    '/api/projects/:team_id/review_hog/installation_claims/:id/': async ({ request }) => {
                        const { scope } = (await request.json()) as { scope: ReviewInstallationClaimScopeEnumApi }
                        const [installation] = storyState.project.installations
                        storyState.project = { ...storyState.project, installations: [{ ...installation, scope }] }
                        return [200, {}]
                    },
                },
                delete: {
                    '/api/projects/:team_id/review_hog/repository_choices/:id/': ({ params }) => {
                        const name = Object.keys(storyState.choices).find(
                            (key) => storyState.choices[key].id === params.id
                        )
                        if (name) {
                            delete storyState.choices[name]
                        }
                        return [204]
                    },
                    '/api/projects/:team_id/review_hog/repositories/:id/people/:personId/': ({ params }) => {
                        const found = rowById(String(params.id))
                        if (found) {
                            found[1].people = found[1].people.filter((entry) => entry.id !== params.personId)
                        }
                        return [200, {}]
                    },
                    '/api/projects/:team_id/review_hog/project_settings/people/:personId/': ({ params }) => {
                        storyState.project = {
                            ...storyState.project,
                            people: storyState.project.people.filter((entry) => entry.id !== params.personId),
                        }
                        return [200, storyState.project]
                    },
                },
            })(Story, context)
        },
    ],
}
export default meta

type Story = StoryObj<typeof CodeReviewScene>

export const Default: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('Review a pull request')).toBeVisible()
        await expect(await canvas.findByText('Add retry to the export job')).toBeVisible()
        await expect(canvas.getByText('Mine')).toBeVisible()
        await expect(canvas.queryByText('Review skills')).not.toBeInTheDocument()
        await expect(canvas.getByText('How we review your PRs')).toBeVisible()
    },
}

export const Settings: Story = {
    parameters: { tab: 'settings' },
    play: async ({ canvasElement }) => {
        userLogic.actions.loadUser()
        await waitFor(() => expect(userLogic.values.user?.is_staff).toBe(false))
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('This project reviews example-org:')).toBeVisible()
        await expect(await canvas.findByText('example-org/web')).toBeVisible()
        await expect(canvas.getByText('Reviewed in the Billing project')).toBeVisible()
        await expect(canvas.getByText('You can edit: project admin')).toBeVisible()
        await expect(canvas.getByText('Review skills')).toBeVisible()
        await expect(canvas.getByText('Kept counts: your last 10 Deep reviews')).toBeVisible()
        await expect(canvas.queryByText('Review a pull request')).not.toBeInTheDocument()
        await expect(canvas.getByLabelText('Resolve comments on my pull requests')).toBeVisible()
    },
}

export const SettingsForMember: Story = {
    parameters: {
        tab: 'settings',
        canEdit: false,
        claimScope: 'selected',
        savedSettings: { default_review_mode: 'flash' },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('Project admins edit')).toBeVisible()
        await expect(
            await canvas.findByText(
                'Your default, On everywhere, applies to your PRs in every repository, except 1 where you picked something else.'
            )
        ).toBeVisible()
        await expect(await canvas.findByText('example-org/web')).toBeVisible()
        await expect(canvas.queryByText('Include in project')).not.toBeInTheDocument()
        await expect(canvas.queryByLabelText('Add exception for example-org/docs')).not.toBeInTheDocument()
    },
}

export const SavedInboxOptIns: Story = {
    parameters: { savedSettings: { review_inbox_prs: true, stamphog_review_inbox_prs: true }, tab: 'settings' },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const inboxLabel = 'Review PRs the agent opens for Inbox reports assigned to me'
        // The Inbox section renders before the settings load and can re-render with new nodes,
        // so query again on every attempt until the saved values arrive.
        await waitFor(() => expect(canvas.getByLabelText(inboxLabel)).toBeChecked(), { timeout: 5000 })
        const inboxSwitch = canvas.getByLabelText(inboxLabel)
        const stamphogSwitch = canvas.getByLabelText('Let Stamphog review my Inbox PRs')
        await expect(inboxSwitch).toBeEnabled()
        await expect(stamphogSwitch).toBeChecked()
        await expect(stamphogSwitch).toBeEnabled()
    },
}

export const FlagDisabledForStaff: Story = {
    parameters: { featureFlags: [], isStaff: true },
    play: async ({ canvasElement }) => {
        userLogic.actions.loadUser()
        await waitFor(() => expect(userLogic.values.user?.is_staff).toBe(true))
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('Page not found')).toBeVisible()
        await expect(canvas.queryByText('Review a pull request')).not.toBeInTheDocument()
    },
}

const narrowDecorator: Decorator = (Story): JSX.Element => (
    <div className="max-w-130">
        <Story />
    </div>
)

export const Narrow: Story = {
    decorators: [narrowDecorator],
}

export const NarrowSettings: Story = {
    parameters: { tab: 'settings' },
    decorators: [narrowDecorator],
}
