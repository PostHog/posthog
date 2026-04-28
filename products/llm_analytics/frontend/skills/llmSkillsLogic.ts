import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { ApiConfig } from '~/lib/api'
import { Sorting } from '~/lib/lemon-ui/LemonTable'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { tabAwareActionToUrl } from '~/lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from '~/lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual } from '~/lib/utils'
import { sceneLogic } from '~/scenes/sceneLogic'
import { urls } from '~/scenes/urls'

import { llmSkillsList, llmSkillsNameArchiveCreate, llmSkillsNameDuplicateCreate } from '../generated/api'
import type { LLMSkillListApi, PaginatedLLMSkillListListApi } from '../generated/api.schemas'
import type { llmSkillsLogicType } from './llmSkillsLogicType'

export const SKILLS_PER_PAGE = 30
// Hard upper bound for "group by prefix" mode — grouping is a client-side aggregation,
// so we fetch the full list once instead of paging.
export const SKILLS_GROUP_LIMIT = 500
// Cap on hierarchical nesting depth. Pathological chains like a-b-c-d-e-f-g-h would
// otherwise push content infinitely right; remaining segments below this depth render
// as leaves of the deepest allowed group.
export const SKILLS_GROUP_MAX_DEPTH = 4
export const LLM_SKILLS_FORCE_RELOAD_PARAM = 'llm_skills_force_reload'

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

export interface LLMSkillsLogicProps {
    tabId?: string
}

export const llmSkillsLogic = kea<llmSkillsLogicType>([
    path(['scenes', 'llm-analytics', 'llmSkillsLogic']),
    props({} as LLMSkillsLogicProps),
    key((props) => props.tabId ?? 'default'),

    actions({
        setFilters: (filters: Partial<SkillFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadSkills: (debounce: boolean = true) => ({ debounce }),
        deleteSkill: (skillName: string) => ({ skillName }),
        duplicateSkill: (skillName: string, newName: string) => ({ skillName, newName }),
    }),

    reducers({
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
                    const params = filters.group_by_prefix
                        ? {
                              search: filters.search,
                              order_by: filters.order_by,
                              offset: 0,
                              limit: SKILLS_GROUP_LIMIT,
                              created_by_id: filters.created_by_id,
                          }
                        : {
                              search: filters.search,
                              order_by: filters.order_by,
                              offset: Math.max(0, (filters.page - 1) * SKILLS_PER_PAGE),
                              limit: SKILLS_PER_PAGE,
                              created_by_id: filters.created_by_id,
                          }

                    if (
                        !filters.group_by_prefix &&
                        sceneLogic.findMounted()?.values.activeSceneId === 'LLMAnalytics' &&
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
    })),

    selectors({
        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<SkillFilters> | null): SkillFilters => cleanFilters(rawFilters || {}),
        ],

        count: [(s) => [s.skills], (skills: PaginatedLLMSkillListListApi) => skills.count],

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

    listeners(({ asyncActions, values, selectors }) => ({
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
                router.actions.push(urls.llmAnalyticsSkill(newName))
            } catch (e) {
                console.error('Failed to duplicate skill', e)
                lemonToast.error('Failed to duplicate skill')
            }
        },
    })),

    tabAwareActionToUrl(({ values }) => {
        const changeUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] | void => {
            const nextValues = cleanFilterUrlParams(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)

            if (!objectsEqual(values.filters, urlValues)) {
                return [urls.llmAnalyticsSkills(), nextValues, {}, { replace: true }]
            }
        }

        return { setFilters: changeUrl }
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.llmAnalyticsSkills()]: (_, searchParams, __, { method }) => {
            const newFilters = cleanFilters(searchParams)
            const forceReload = typeof searchParams?.[LLM_SKILLS_FORCE_RELOAD_PARAM] === 'string'
            if (!objectsEqual(values.filters, newFilters)) {
                actions.setFilters(newFilters, false)
            } else if (forceReload || method !== 'REPLACE') {
                actions.loadSkills(false)
            }

            if (forceReload) {
                const nextSearchParams = { ...searchParams }
                delete nextSearchParams[LLM_SKILLS_FORCE_RELOAD_PARAM]
                router.actions.replace(urls.llmAnalyticsSkills(), nextSearchParams)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSkills()
    }),
])
