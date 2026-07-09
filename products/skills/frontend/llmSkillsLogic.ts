import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { objectsEqual } from 'lib/utils/objects'

import api, { ApiConfig } from '~/lib/api'
import { downloadBlob } from '~/lib/components/ExportButton/exporter'
import { Sorting } from '~/lib/lemon-ui/LemonTable'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { trackedActionToUrl } from '~/lib/logic/scenes/trackedActionToUrl'
import { sceneLogic } from '~/scenes/sceneLogic'
import { urls } from '~/scenes/urls'

import {
    getLlmSkillsNameExportRetrieveUrl,
    llmSkillsImportCreate,
    llmSkillsList,
    llmSkillsMarketplaceInstallCommandCreate,
    llmSkillsMarketplaceInstallCommandRetrieve,
    llmSkillsNameArchiveCreate,
    llmSkillsNameDuplicateCreate,
} from 'products/skills/frontend/generated/api'
import type {
    LLMSkillListApi,
    LLMSkillMarketplaceCommandApi,
    PaginatedLLMSkillListListApi,
} from 'products/skills/frontend/generated/api.schemas'

import type { llmSkillsLogicType } from './llmSkillsLogicType'

/** Builds the `/plugin marketplace add` command. The token is embedded once minted; until then
 * a placeholder is shown. */
export function buildMarketplaceCommand(token: string | null): string {
    const teamId = ApiConfig.getCurrentTeamId()
    const origin = window.location.origin
    const scheme = origin.startsWith('https') ? 'https' : 'http'
    const host = origin.replace(/^https?:\/\//, '')
    return `/plugin marketplace add ${scheme}://x-access-token:${token ?? 'YOUR_PHS_TOKEN'}@${host}/api/projects/${teamId}/llm_skills/marketplace.git`
}

function errorDetail(error: unknown): string | undefined {
    return error !== null && typeof error === 'object' && 'detail' in error
        ? (error as { detail?: string }).detail
        : undefined
}

/** Download a skill as a spec-compliant zip. The generated export client JSON-parses the
 * binary response, so fetch the raw blob via the generated URL builder instead. */
export async function exportAndDownloadSkill(skillName: string): Promise<void> {
    const url = getLlmSkillsNameExportRetrieveUrl(String(ApiConfig.getCurrentTeamId()), skillName, {})
    const response = await api.getResponse(url)
    if (!response.ok) {
        let detail = 'Failed to export skill'
        try {
            detail = (await response.json())?.detail || detail
        } catch {
            // non-JSON error body; keep the default message
        }
        throw new Error(detail)
    }
    downloadBlob(await response.blob(), `${skillName}.zip`)
}

export const SKILLS_PER_PAGE = 30
// Hard upper bound for "group by prefix" mode — grouping is a client-side aggregation,
// so we fetch the full list once instead of paging.
export const SKILLS_GROUP_LIMIT = 500
// Cap on hierarchical nesting depth. Pathological chains like a-b-c-d-e-f-g-h would
// otherwise push content infinitely right; remaining segments below this depth render
// as leaves of the deepest allowed group.
export const SKILLS_GROUP_MAX_DEPTH = 4
export const LLM_SKILLS_FORCE_RELOAD_PARAM = 'llm_skills_force_reload'

/** URL/UI key for the default tab — the uncategorized skills (everything not pulled into a category tab). */
export const DEFAULT_SKILLS_TAB_KEY: string = 'skills'

/** Sub-title shown for the default "Skills" tab. Category tabs carry their own copy (below). */
export const DEFAULT_SKILLS_TAB_DESCRIPTION = 'Manage versioned agent skills that any agent can discover and use.'

export interface SkillCategoryTab {
    /** Tab key, also the `/skills/<key>` URL segment. */
    key: string
    /** The `LLMSkill.category` value this tab filters to. */
    category: string
    label: string
    /** Sub-title shown under the scene title while this tab is active. */
    description: string
}

/**
 * Category-backed tabs shown alongside the default "Skills" tab. Each entry surfaces one
 * `LLMSkill.category` value as its own tab and removes it from the default list (which only shows
 * uncategorized skills). To add a tab — e.g. official AI-plugin skills — add an entry here, register
 * the matching `/skills/<key>` route in manifest.tsx, and have the producer stamp that `category`.
 */
export const SKILL_CATEGORY_TABS: SkillCategoryTab[] = [
    {
        key: 'scouts',
        category: 'scout',
        label: 'Scouts',
        description:
            "Scouts — scheduled agents that scan your project and surface findings in your inbox. Includes PostHog's canonical scouts and any custom ones you author.",
    },
]

export function skillCategoryForTabKey(tabKey: string): string {
    return SKILL_CATEGORY_TABS.find((tab) => tab.key === tabKey)?.category ?? ''
}

export function skillTabDescription(tabKey: string): string {
    return SKILL_CATEGORY_TABS.find((tab) => tab.key === tabKey)?.description ?? DEFAULT_SKILLS_TAB_DESCRIPTION
}

/** The `/skills` or `/skills/<categoryKey>` path for a tab key. */
export function skillTabUrl(tabKey: string): string {
    return tabKey === DEFAULT_SKILLS_TAB_KEY ? urls.skills() : urls.skillsCategoryTab(tabKey)
}

export interface SkillFilters {
    page: number
    search: string
    order_by: string
    group_by_prefix: boolean
    created_by_id?: number
}

function parseBoolean(value: unknown): boolean {
    if (typeof value === 'boolean') {
        return value
    }
    if (typeof value === 'string') {
        return value === 'true' || value === '1'
    }
    return false
}

function cleanFilters(values: Partial<SkillFilters>): SkillFilters {
    return {
        page: parseInt(String(values.page)) || 1,
        search: String(values.search || ''),
        order_by: values.order_by || '-created_at',
        group_by_prefix: parseBoolean(values.group_by_prefix),
        created_by_id: values.created_by_id ? Number(values.created_by_id) : undefined,
    }
}

function cleanFilterUrlParams(filters: SkillFilters): Record<string, unknown> {
    return {
        page: filters.page === 1 || filters.group_by_prefix ? undefined : filters.page,
        search: filters.search || undefined,
        order_by: filters.order_by === '-created_at' ? undefined : filters.order_by,
        group_by_prefix: filters.group_by_prefix ? 'true' : undefined,
        created_by_id: filters.created_by_id,
    }
}

export interface SkillGroupNode {
    /** Full prefix path joined by '-', e.g. "andy-signals". */
    prefix: string
    /** Last segment of the prefix, e.g. "signals". */
    segment: string
    /** Total skills under this group (including all descendants). */
    count: number
    /** Sub-groups nested below this one (only created when 2+ skills share a deeper prefix). */
    children: SkillGroupNode[]
    /** Skills that belong directly to this group with no further sub-grouping. */
    leaves: LLMSkillListApi[]
}

export interface SkillGroupTree {
    groups: SkillGroupNode[]
    /** Top-level skills that didn't share a prefix with anything else. */
    ungrouped: LLMSkillListApi[]
}

function buildGroupTree(skills: LLMSkillListApi[], depth: number, pathPrefix: string): SkillGroupTree {
    const buckets = new Map<string, LLMSkillListApi[]>()
    const directLeaves: LLMSkillListApi[] = []

    for (const skill of skills) {
        const segments = skill.name.split('-')
        if (depth >= segments.length) {
            directLeaves.push(skill)
            continue
        }
        const key = segments[depth]
        const list = buckets.get(key) ?? []
        list.push(skill)
        buckets.set(key, list)
    }

    const groups: SkillGroupNode[] = []
    const leaves: LLMSkillListApi[] = [...directLeaves]

    for (const [segment, items] of buckets) {
        if (items.length < 2) {
            // Lone matches at this depth roll up as leaves of the parent group.
            leaves.push(...items)
            continue
        }
        const newPrefix = pathPrefix ? `${pathPrefix}-${segment}` : segment
        // At max depth, stop recursing — collapse all remaining items into leaves of this group.
        const sub: SkillGroupTree =
            depth + 1 >= SKILLS_GROUP_MAX_DEPTH
                ? { groups: [], ungrouped: [...items].sort((a, b) => a.name.localeCompare(b.name)) }
                : buildGroupTree(items, depth + 1, newPrefix)
        groups.push({
            prefix: newPrefix,
            segment,
            count: items.length,
            children: sub.groups,
            leaves: sub.ungrouped,
        })
    }

    groups.sort((a, b) => b.count - a.count || a.segment.localeCompare(b.segment))
    leaves.sort((a, b) => a.name.localeCompare(b.name))

    return { groups, ungrouped: leaves }
}

export function groupSkillsByPrefix(skills: LLMSkillListApi[]): SkillGroupTree {
    return buildGroupTree(skills, 0, '')
}

export type LLMSkillsLogicProps = Record<string, never>

export const llmSkillsLogic = kea<llmSkillsLogicType>([
    path(['scenes', 'skills', 'llmSkillsLogic']),
    props({} as LLMSkillsLogicProps),

    actions({
        setFilters: (filters: Partial<SkillFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadSkills: (debounce: boolean = true) => ({ debounce }),
        loadCategoryCounts: true,
        setActiveTab: (tabKey: string) => ({ tabKey }),
        deleteSkill: (skillName: string) => ({ skillName }),
        duplicateSkill: (skillName: string, newName: string) => ({ skillName, newName }),
        importSkill: (file: File) => ({ file }),
        setImporting: (importing: boolean) => ({ importing }),
        downloadSkillZip: (skillName: string) => ({ skillName }),
        setConnectModalOpen: (open: boolean) => ({ open }),
        loadMarketplaceState: true,
        // rotate=false mints when absent / returns the masked existing key; rotate=true rolls it.
        issueMarketplaceCommand: (rotate: boolean = false) => ({ rotate }),
        setMarketplaceState: (state: LLMSkillMarketplaceCommandApi | null) => ({ state }),
        setMarketplaceLoading: (loading: boolean) => ({ loading }),
        setIssuingCredential: (issuing: boolean) => ({ issuing }),
    }),

    reducers({
        activeTabKey: [
            DEFAULT_SKILLS_TAB_KEY,
            {
                setActiveTab: (_, { tabKey }) => tabKey,
            },
        ],
        rawFilters: [
            null as Partial<SkillFilters> | null,
            {
                setFilters: (state, { filters, merge }) =>
                    cleanFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        ...('page' in filters ? {} : { page: 1 }),
                    }),
            },
        ],
        importing: [
            false,
            {
                setImporting: (_, { importing }) => importing,
            },
        ],
        connectModalOpen: [
            false,
            {
                setConnectModalOpen: (_, { open }) => open,
            },
        ],
        // The full server response (status, command, command_template, token, mask). The live phs_
        // token only ever lives here and only on create/rotate; clear it when the modal closes.
        marketplaceState: [
            null as LLMSkillMarketplaceCommandApi | null,
            {
                setMarketplaceState: (_, { state }) => state,
                setConnectModalOpen: (state, { open }) => (open ? state : null),
            },
        ],
        marketplaceLoading: [
            false,
            {
                setMarketplaceLoading: (_, { loading }) => loading,
            },
        ],
        issuingCredential: [
            false,
            {
                setIssuingCredential: (_, { issuing }) => issuing,
            },
        ],
    }),

    loaders(({ values }) => ({
        skills: [
            { results: [], count: 0 } as PaginatedLLMSkillListListApi,
            {
                loadSkills: async ({ debounce }, breakpoint) => {
                    if (debounce && values.skills.results.length > 0) {
                        await breakpoint(300)
                    }

                    const { filters } = values
                    // Always send `category` (even as ""): the default tab shows uncategorized skills,
                    // each category tab shows its own category. Presence of the param is the filter.
                    const category = values.activeCategory
                    const params = filters.group_by_prefix
                        ? {
                              search: filters.search,
                              order_by: filters.order_by,
                              offset: 0,
                              limit: SKILLS_GROUP_LIMIT,
                              created_by_id: filters.created_by_id,
                              category,
                          }
                        : {
                              search: filters.search,
                              order_by: filters.order_by,
                              offset: Math.max(0, (filters.page - 1) * SKILLS_PER_PAGE),
                              limit: SKILLS_PER_PAGE,
                              created_by_id: filters.created_by_id,
                              category,
                          }

                    if (
                        !filters.group_by_prefix &&
                        sceneLogic.findMounted()?.values.activeSceneId === 'AIObservability' &&
                        router.values.lastMethod !== 'POP' &&
                        values.skills.results.length > 0 &&
                        values.rawFilters?.page !== filters.page
                    ) {
                        window.scrollTo(0, 0)
                    }

                    return await llmSkillsList(String(ApiConfig.getCurrentTeamId()), params)
                },
            },
        ],
        // Per-category skill counts, used to decide which category tabs to show. Loaded once on
        // mount (and after a delete) with a cheap limit=1 probe per category — we only read `count`.
        categoryCounts: [
            {} as Record<string, number>,
            {
                loadCategoryCounts: async () => {
                    const teamId = String(ApiConfig.getCurrentTeamId())
                    const entries = await Promise.all(
                        SKILL_CATEGORY_TABS.map(async (tab) => {
                            const { count } = await llmSkillsList(teamId, {
                                category: tab.category,
                                limit: 1,
                                offset: 0,
                            })
                            return [tab.category, count] as const
                        })
                    )
                    return Object.fromEntries(entries)
                },
            },
        ],
    })),

    selectors({
        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<SkillFilters> | null): SkillFilters => cleanFilters(rawFilters || {}),
        ],

        activeCategory: [
            (s) => [s.activeTabKey],
            (activeTabKey: string): string => skillCategoryForTabKey(activeTabKey),
        ],

        activeTabDescription: [
            (s) => [s.activeTabKey],
            (activeTabKey: string): string => skillTabDescription(activeTabKey),
        ],

        // A category tab is shown only once the team has at least one skill in that category.
        // The active tab is always kept visible so direct navigation to /skills/<key> (or deleting
        // the last skill while viewing the tab) doesn't strand the user on a tab that isn't listed.
        visibleCategoryTabs: [
            (s) => [s.categoryCounts, s.activeTabKey],
            (categoryCounts: Record<string, number>, activeTabKey: string): SkillCategoryTab[] =>
                SKILL_CATEGORY_TABS.filter(
                    (tab) => (categoryCounts[tab.category] ?? 0) > 0 || tab.key === activeTabKey
                ),
        ],

        count: [(s) => [s.skills], (skills: PaginatedLLMSkillListListApi) => skills.count],

        marketplaceCommand: [
            (s) => [s.marketplaceState],
            (marketplaceState: LLMSkillMarketplaceCommandApi | null): string =>
                // Live command (token embedded) once issued, else the server placeholder template,
                // else a locally-built placeholder before the state has loaded.
                marketplaceState?.command ?? marketplaceState?.command_template ?? buildMarketplaceCommand(null),
        ],

        codexCommand: [
            (s) => [s.marketplaceState],
            (marketplaceState: LLMSkillMarketplaceCommandApi | null): string =>
                // Same per-user credential; the Codex two-line command. Only shown once state loads.
                marketplaceState?.codex_command ?? marketplaceState?.codex_command_template ?? '',
        ],

        sorting: [
            (s) => [s.filters],
            (filters: SkillFilters): Sorting | null => {
                if (!filters.order_by) {
                    return { columnKey: 'created_at', order: -1 }
                }

                return filters.order_by.startsWith('-')
                    ? { columnKey: filters.order_by.slice(1), order: -1 }
                    : { columnKey: filters.order_by, order: 1 }
            },
        ],

        pagination: [
            (s) => [s.filters, s.count],
            (filters: SkillFilters, count: number): PaginationManual | undefined => {
                if (filters.group_by_prefix) {
                    return undefined
                }
                return {
                    controlled: true,
                    pageSize: SKILLS_PER_PAGE,
                    currentPage: filters.page,
                    entryCount: count,
                }
            },
        ],

        groupedSkills: [
            (s) => [s.skills, s.filters],
            (skills: PaginatedLLMSkillListListApi, filters: SkillFilters): SkillGroupTree | null => {
                if (!filters.group_by_prefix) {
                    return null
                }
                return groupSkillsByPrefix(skills.results)
            },
        ],

        skillCountLabel: [
            (s) => [s.filters, s.count, s.skills],
            (filters: SkillFilters, count: number, skills: PaginatedLLMSkillListListApi) => {
                if (filters.group_by_prefix) {
                    const loaded = skills.results.length
                    if (count === 0) {
                        return '0 skills'
                    }
                    if (loaded < count) {
                        return `Showing ${loaded} of ${count} skill${count === 1 ? '' : 's'}`
                    }
                    return `${count} skill${count === 1 ? '' : 's'}`
                }
                const start = (filters.page - 1) * SKILLS_PER_PAGE + 1
                const end = Math.min(filters.page * SKILLS_PER_PAGE, count)

                return count === 0 ? '0 skills' : `${start}-${end} of ${count} skill${count === 1 ? '' : 's'}`
            },
        ],
    }),

    listeners(({ actions, asyncActions, values, selectors }) => ({
        setFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const { filters } = values

            if (!objectsEqual(oldFilters, filters)) {
                await asyncActions.loadSkills(debounce)
            }
        },

        deleteSkill: async ({ skillName }) => {
            try {
                await llmSkillsNameArchiveCreate(String(ApiConfig.getCurrentTeamId()), skillName)
                lemonToast.info(`${skillName || 'Skill'} has been archived.`)
                await asyncActions.loadSkills(false)
                // Archiving may have removed the last skill in a category — refresh tab visibility.
                actions.loadCategoryCounts()
            } catch (e) {
                console.error('Failed to archive skill', e)
                lemonToast.error('Failed to archive skill')
            }
        },

        duplicateSkill: async ({ skillName, newName }) => {
            try {
                await llmSkillsNameDuplicateCreate(String(ApiConfig.getCurrentTeamId()), skillName, {
                    new_name: newName,
                })
                lemonToast.success(`Skill duplicated as "${newName}".`)
                router.actions.push(urls.skill(newName))
            } catch (e) {
                console.error('Failed to duplicate skill', e)
                lemonToast.error('Failed to duplicate skill')
            }
        },

        importSkill: async ({ file }) => {
            actions.setImporting(true)
            try {
                // Orval types the FileField as string; the generated client appends the File to FormData.
                const skill = await llmSkillsImportCreate(String(ApiConfig.getCurrentTeamId()), {
                    file: file as unknown as string,
                })
                lemonToast.success(`Imported "${skill.name}".`)
                actions.loadSkills(false)
                router.actions.push(urls.skill(skill.name))
            } catch (e) {
                console.error('Failed to import skill', e)
                lemonToast.error(errorDetail(e) || 'Failed to import skill — is it a valid skill zip?')
            } finally {
                actions.setImporting(false)
            }
        },

        downloadSkillZip: async ({ skillName }) => {
            try {
                await exportAndDownloadSkill(skillName)
            } catch (e) {
                console.error('Failed to export skill', e)
                lemonToast.error(errorDetail(e) || (e instanceof Error ? e.message : 'Failed to export skill'))
            }
        },

        setConnectModalOpen: ({ open }) => {
            // Reload the (token-less) connection state each time the modal opens so we never
            // re-surface a previously minted token and always reflect the current credential.
            if (open) {
                actions.loadMarketplaceState()
            }
        },

        loadMarketplaceState: async () => {
            actions.setMarketplaceLoading(true)
            try {
                const state = await llmSkillsMarketplaceInstallCommandRetrieve(String(ApiConfig.getCurrentTeamId()))
                actions.setMarketplaceState(state)
            } catch (e) {
                console.error('Failed to load marketplace connection state', e)
                lemonToast.error(errorDetail(e) || 'Failed to check your skill store connection.')
            } finally {
                actions.setMarketplaceLoading(false)
            }
        },

        issueMarketplaceCommand: async ({ rotate }) => {
            actions.setIssuingCredential(true)
            try {
                // Per-user read-only credential: mints if absent, rolls (rotate=true) only this user's own key.
                const state = await llmSkillsMarketplaceInstallCommandCreate(String(ApiConfig.getCurrentTeamId()), {
                    rotate,
                })
                actions.setMarketplaceState(state)
            } catch (e) {
                console.error('Failed to issue marketplace credential', e)
                lemonToast.error(
                    errorDetail(e) || 'Failed to issue credential. Do you have permission to manage API keys?'
                )
            } finally {
                actions.setIssuingCredential(false)
            }
        },
    })),

    trackedActionToUrl(({ values }) => {
        const changeUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] | void => {
            const nextValues = cleanFilterUrlParams(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)

            if (!objectsEqual(values.filters, urlValues)) {
                // Keep filter changes on the active tab's path so editing search/sort on a category
                // tab doesn't bounce the URL back to the default /skills.
                return [skillTabUrl(values.activeTabKey), nextValues, {}, { replace: true }]
            }
        }

        return { setFilters: changeUrl }
    }),

    urlToAction(({ actions, values }) => {
        const handleTab =
            (tabKey: string) =>
            (_: any, searchParams: Record<string, any>, __: any, { method }: { method: string }): void => {
                // Update the active tab first so the loader picks up the new category. Setting it is a
                // plain reducer (no reload of its own) — handleTab owns the single reload below.
                const tabChanged = values.activeTabKey !== tabKey
                if (tabChanged) {
                    actions.setActiveTab(tabKey)
                }
                const newFilters = cleanFilters(searchParams)
                const forceReload = typeof searchParams?.[LLM_SKILLS_FORCE_RELOAD_PARAM] === 'string'
                if (!objectsEqual(values.filters, newFilters)) {
                    // setFilters reloads, reading the just-updated activeCategory.
                    actions.setFilters(newFilters, false)
                } else if (tabChanged || forceReload || method !== 'REPLACE') {
                    actions.loadSkills(false)
                }

                if (forceReload) {
                    const nextSearchParams = { ...searchParams }
                    delete nextSearchParams[LLM_SKILLS_FORCE_RELOAD_PARAM]
                    router.actions.replace(skillTabUrl(tabKey), nextSearchParams)
                }
            }

        return {
            [urls.skills()]: handleTab(DEFAULT_SKILLS_TAB_KEY),
            ...Object.fromEntries(SKILL_CATEGORY_TABS.map((tab) => [skillTabUrl(tab.key), handleTab(tab.key)])),
        }
    }),

    afterMount(({ actions }) => {
        actions.loadSkills()
        actions.loadCategoryCounts()
    }),
])
