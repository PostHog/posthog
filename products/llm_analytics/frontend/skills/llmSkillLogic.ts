import { actions, afterMount, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { combineUrl, router } from 'kea-router'

import { ApiConfig } from '~/lib/api'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { tabAwareUrlToAction } from '~/lib/logic/scenes/tabAwareUrlToAction'
import { urls } from '~/scenes/urls'
import { Breadcrumb } from '~/types'

import {
    llmSkillsCreate,
    llmSkillsNameArchiveCreate,
    llmSkillsNameFilesRetrieve,
    llmSkillsNamePartialUpdate,
    llmSkillsResolveNameRetrieve,
} from '../generated/api'
import type {
    LLMSkillApi,
    LLMSkillFileApi,
    LLMSkillFileInputApi,
    LLMSkillListApi,
    LLMSkillVersionSummaryApi,
} from '../generated/api.schemas'
import type { llmSkillLogicType } from './llmSkillLogicType'
import { llmSkillsLogic, LLM_SKILLS_FORCE_RELOAD_PARAM } from './llmSkillsLogic'
import { SKILL_DESCRIPTION_MAX_LENGTH, validateSkillName } from './skillConstants'

export enum SkillMode {
    View = 'view',
    Edit = 'edit',
}

export interface SkillLogicProps {
    skillName: string | 'new'
    mode?: SkillMode
    selectedVersion?: number | null
    tabId?: string
}

export interface SkillFormFileValues {
    path: string
    content: string
    content_type: string
}

export interface SkillFormValues {
    name: string
    description: string
    body: string
    license: string
    compatibility: string
    files: SkillFormFileValues[]
}

export interface ResolvedLLMSkill extends LLMSkillApi {
    versions: LLMSkillVersionSummaryApi[]
    has_more: boolean
}

export function isSkill(skill: LLMSkillApi | ResolvedLLMSkill | SkillFormValues | null): skill is ResolvedLLMSkill {
    return skill !== null && 'id' in skill
}

const DEFAULT_SKILL_FORM_VALUES: SkillFormValues = {
    name: '',
    description: '',
    body: '',
    license: '',
    compatibility: '',
    files: [],
}

const SKILL_VERSIONS_LIMIT = 50

async function fetchResolvedSkill(
    skillName: string,
    params?: { version?: number; offset?: number; before_version?: number; limit?: number }
): Promise<ResolvedLLMSkill> {
    const response = await llmSkillsResolveNameRetrieve(String(ApiConfig.getCurrentTeamId()), skillName, {
        ...params,
        limit: params?.limit ?? SKILL_VERSIONS_LIMIT,
    })
    return {
        ...response.skill,
        versions: response.versions,
        has_more: response.has_more,
    }
}

function getSkillFormDefaults(skill: LLMSkillApi, fileContents?: LLMSkillFileApi[]): SkillFormValues {
    const files: SkillFormFileValues[] = fileContents
        ? fileContents.map((f) => ({ path: f.path, content: f.content, content_type: f.content_type || 'text/plain' }))
        : skill.files.map((f) => ({ path: f.path, content: '', content_type: f.content_type || 'text/plain' }))
    return {
        name: skill.name,
        description: skill.description,
        body: skill.body,
        license: skill.license || '',
        compatibility: skill.compatibility || '',
        files,
    }
}

async function fetchAllFileContents(skillName: string, skill: LLMSkillApi): Promise<LLMSkillFileApi[]> {
    if (!skill.files || skill.files.length === 0) {
        return []
    }
    const teamId = String(ApiConfig.getCurrentTeamId())
    const results = await Promise.all(
        skill.files.map((f) =>
            llmSkillsNameFilesRetrieve(teamId, skillName, f.path, {
                version: skill.is_latest ? undefined : skill.version,
            })
        )
    )
    return results
}

function findExistingSkill(skillName: string): LLMSkillListApi | undefined {
    return llmSkillsLogic.findMounted()?.values.skills.results.find((s) => s.name === skillName)
}

export const llmSkillLogic = kea<llmSkillLogicType>([
    path(['scenes', 'llm-analytics', 'llmSkillLogic']),
    props({ skillName: 'new' } as SkillLogicProps),
    key(
        ({ skillName, selectedVersion, tabId }) =>
            `skill-${skillName}:${selectedVersion ?? 'latest'}::${tabId ?? 'default'}`
    ),
    actions({
        setSkill: (skill: ResolvedLLMSkill | SkillFormValues) => ({ skill }),
        deleteSkill: true,
        loadMoreVersions: true,
        setVersionsLoading: (versionsLoading: boolean) => ({ versionsLoading }),
        setMode: (mode: SkillMode) => ({ mode }),
        loadFileContents: true,
        setFileContentsLoading: (loading: boolean) => ({ loading }),
        toggleOutlineExpanded: true,
    }),

    reducers(({ props }) => ({
        skill: [
            null as ResolvedLLMSkill | SkillFormValues | null,
            {
                loadSkillSuccess: (_, { skill }) => skill,
                setSkill: (_, { skill }) => skill,
            },
        ],
        skillFetched: [
            props.skillName === 'new',
            {
                loadSkillSuccess: () => true,
                loadSkillFailure: () => true,
            },
        ],
        versionsLoading: [
            false,
            {
                loadMoreVersions: () => true,
                setVersionsLoading: (_, { versionsLoading }) => versionsLoading,
                loadSkillSuccess: () => false,
            },
        ],
        fileContentsLoading: [
            false,
            {
                loadFileContents: () => true,
                setFileContentsLoading: (_, { loading }) => loading,
            },
        ],
        isOutlineExpanded: [
            false,
            {
                toggleOutlineExpanded: (state) => !state,
            },
        ],
        mode: [
            props.mode ?? SkillMode.View,
            {
                setMode: (_, { mode }) => mode,
            },
        ],
    })),

    loaders(({ props }) => ({
        skill: {
            __default: null as ResolvedLLMSkill | SkillFormValues | null,
            loadSkill: async () =>
                fetchResolvedSkill(props.skillName, {
                    version: props.selectedVersion ?? undefined,
                }),
        },
    })),

    forms(({ actions, props, values }) => ({
        skillForm: {
            defaults: DEFAULT_SKILL_FORM_VALUES,
            options: { showErrorsOnTouch: true },

            errors: ({ name, description, body }) => ({
                name: validateSkillName(name),
                description: !description?.trim()
                    ? 'Description is required'
                    : description.length > SKILL_DESCRIPTION_MAX_LENGTH
                      ? `Description must be ${SKILL_DESCRIPTION_MAX_LENGTH} characters or fewer`
                      : undefined,
                body: !body?.trim() ? 'Skill body is required' : undefined,
            }),

            submit: async (formValues) => {
                const isNew = props.skillName === 'new'

                try {
                    let savedSkill: LLMSkillApi

                    const filesToSend: LLMSkillFileInputApi[] | undefined =
                        formValues.files.length > 0
                            ? formValues.files.map((f) => ({
                                  path: f.path,
                                  content: f.content,
                                  content_type: f.content_type || undefined,
                              }))
                            : undefined

                    if (isNew) {
                        const createResponse = await llmSkillsCreate(String(ApiConfig.getCurrentTeamId()), {
                            name: formValues.name,
                            description: formValues.description,
                            body: formValues.body,
                            license: formValues.license || undefined,
                            compatibility: formValues.compatibility || undefined,
                            files: filesToSend,
                        })
                        savedSkill = { ...createResponse, files: [] }
                        llmSkillsLogic.findMounted()?.actions.loadSkills(false)
                        lemonToast.success('Skill created successfully')
                        router.actions.replace(urls.llmAnalyticsSkill(savedSkill.name))
                    } else {
                        const currentSkill = values.skill

                        if (!isSkill(currentSkill)) {
                            throw new Error('Cannot publish skill version: skill data not loaded')
                        }

                        savedSkill = await llmSkillsNamePartialUpdate(
                            String(ApiConfig.getCurrentTeamId()),
                            props.skillName,
                            {
                                body: formValues.body,
                                description: formValues.description,
                                license: formValues.license || undefined,
                                compatibility: formValues.compatibility || undefined,
                                allowed_tools: currentSkill.allowed_tools,
                                metadata: currentSkill.metadata,
                                base_version: currentSkill.latest_version,
                                files: filesToSend,
                            }
                        )
                        llmSkillsLogic.findMounted()?.actions.loadSkills(false)
                        lemonToast.success('Skill version published successfully')

                        actions.setSkill({
                            ...savedSkill,
                            versions: [
                                {
                                    id: savedSkill.id,
                                    version: savedSkill.version,
                                    created_by: savedSkill.created_by,
                                    created_at: savedSkill.created_at,
                                    is_latest: true,
                                },
                                ...currentSkill.versions
                                    .filter((v) => v.id !== savedSkill.id)
                                    .map((v) => ({ ...v, is_latest: false })),
                            ],
                            has_more: currentSkill.has_more,
                        })
                        actions.setSkillFormValues(getSkillFormDefaults(savedSkill))
                        router.actions.replace(urls.llmAnalyticsSkill(props.skillName))

                        try {
                            const latest = await fetchResolvedSkill(props.skillName)
                            actions.setSkill(latest)
                            actions.setSkillFormValues(getSkillFormDefaults(latest))
                        } catch (err) {
                            console.error('Failed to refresh skill after publish', err)
                        }
                    }

                    actions.setMode(SkillMode.View)
                    if (isNew) {
                        actions.setSkill({
                            ...savedSkill,
                            versions: [],
                            has_more: false,
                        })
                        actions.setSkillFormValues(getSkillFormDefaults(savedSkill))
                    }
                } catch (error: unknown) {
                    const detail =
                        error !== null && typeof error === 'object' && 'detail' in error
                            ? (error as { detail: string }).detail
                            : undefined
                    lemonToast.error(detail || 'Failed to save skill')
                    throw error
                }
            },
        },
    })),

    selectors({
        isNewSkill: [() => [(_, props) => props], (props) => props.skillName === 'new'],

        isSkillMissing: [
            (s) => [s.skill, s.skillLoading, s.skillFetched],
            (skill, skillLoading, skillFetched) => skillFetched && !skillLoading && skill === null,
        ],

        shouldDisplaySkeleton: [
            (s) => [s.skill, s.skillLoading, s.skillFetched, s.isNewSkill],
            (skill, skillLoading, skillFetched, isNewSkill) =>
                !isNewSkill && (!skillFetched || (skillLoading && skill === null)),
        ],

        isHistoricalVersion: [(s) => [s.skill], (skill) => (isSkill(skill) ? !skill.is_latest : false)],

        breadcrumbs: [
            (s) => [s.skill, router.selectors.searchParams],
            (skill: LLMSkillApi | SkillFormValues | null, searchParams: Record<string, any>): Breadcrumb[] => [
                {
                    name: 'Skills',
                    path: combineUrl(urls.llmAnalyticsSkills(), searchParams).url,
                    key: 'LLMAnalyticsSkills',
                },
                {
                    name:
                        skill && 'name' in skill
                            ? isSkill(skill)
                                ? `${skill.name} v${skill.version}`
                                : skill.name || 'New skill'
                            : 'New skill',
                    key: 'LLMAnalyticsSkill',
                },
            ],
        ],

        isViewMode: [
            (s) => [s.mode, (_, props) => props],
            (mode, props) => props.skillName !== 'new' && mode === SkillMode.View,
        ],

        isEditMode: [
            (s) => [s.mode, (_, props) => props],
            (mode, props) => props.skillName === 'new' || mode === SkillMode.Edit,
        ],

        versions: [(s) => [s.skill], (skill): LLMSkillVersionSummaryApi[] => (isSkill(skill) ? skill.versions : [])],

        canLoadMoreVersions: [(s) => [s.skill], (skill) => (isSkill(skill) ? skill.has_more : false)],
    }),

    listeners(({ actions, props, values }) => ({
        deleteSkill: async () => {
            if (props.skillName !== 'new' && values.skill && isSkill(values.skill)) {
                try {
                    await llmSkillsNameArchiveCreate(String(ApiConfig.getCurrentTeamId()), values.skill.name)
                    lemonToast.info(`${values.skill.name || 'Skill'} has been archived.`)
                    llmSkillsLogic.findMounted()?.actions.loadSkills(false)
                    router.actions.replace(urls.llmAnalyticsSkills(), {
                        ...router.values.searchParams,
                        [LLM_SKILLS_FORCE_RELOAD_PARAM]: String(Date.now()),
                    })
                } catch (e) {
                    console.error('Failed to archive skill', e)
                    lemonToast.error('Failed to archive skill')
                }
            }
        },

        loadMoreVersions: async () => {
            if (props.skillName === 'new' || !isSkill(values.skill)) {
                actions.setVersionsLoading(false)
                return
            }

            try {
                const oldestLoadedVersion = values.skill.versions[values.skill.versions.length - 1]?.version
                if (!oldestLoadedVersion) {
                    actions.setVersionsLoading(false)
                    return
                }

                const response = await fetchResolvedSkill(props.skillName, {
                    version: values.skill.version,
                    before_version: oldestLoadedVersion,
                })

                const existingVersionIds = new Set(values.skill.versions.map((v) => v.id))
                const appendedVersions = response.versions.filter((v) => !existingVersionIds.has(v.id))

                actions.setSkill({
                    ...response,
                    versions: [...values.skill.versions, ...appendedVersions],
                    has_more: response.has_more,
                })
            } catch (e) {
                console.error('Failed to load more versions', e)
                lemonToast.error('Failed to load more versions')
            } finally {
                actions.setVersionsLoading(false)
            }
        },

        loadFileContents: async () => {
            const skill = values.skill
            if (!isSkill(skill) || !skill.files || skill.files.length === 0) {
                actions.setFileContentsLoading(false)
                return
            }
            try {
                const fileContents = await fetchAllFileContents(props.skillName, skill)
                actions.setSkillFormValues({
                    files: fileContents.map((f) => ({
                        path: f.path,
                        content: f.content,
                        content_type: f.content_type || 'text/plain',
                    })),
                })
            } catch (e) {
                console.error('Failed to load file contents for editing', e)
            } finally {
                actions.setFileContentsLoading(false)
            }
        },

        setMode: ({ mode }) => {
            if (
                mode === SkillMode.Edit &&
                isSkill(values.skill) &&
                values.skill.files &&
                values.skill.files.length > 0
            ) {
                actions.loadFileContents()
            }
        },

        loadSkillSuccess: ({ skill }) => {
            if (skill && isSkill(skill)) {
                actions.resetSkillForm()
                actions.setSkillFormValues(getSkillFormDefaults(skill))
            }
        },
    })),

    defaults(
        ({
            props,
        }): {
            skill: SkillFormValues | ResolvedLLMSkill | null
            skillForm: SkillFormValues
            versionsLoading: boolean
        } => {
            if (props.skillName === 'new') {
                return {
                    skill: DEFAULT_SKILL_FORM_VALUES,
                    skillForm: DEFAULT_SKILL_FORM_VALUES,
                    versionsLoading: false,
                }
            }

            const existingSkill = findExistingSkill(props.skillName)

            if (existingSkill) {
                // The list endpoint omits body and files for progressive disclosure; pad
                // them so the cached preview satisfies the full shape until loadSkill runs.
                const paddedSkill: ResolvedLLMSkill = {
                    ...existingSkill,
                    body: '',
                    files: [],
                    versions: [],
                    has_more: false,
                }
                return {
                    skill: paddedSkill,
                    skillForm: getSkillFormDefaults(paddedSkill),
                    versionsLoading: false,
                }
            }

            return {
                skill: null,
                skillForm: DEFAULT_SKILL_FORM_VALUES,
                versionsLoading: false,
            }
        }
    ),

    afterMount(({ actions, values }) => {
        if (values.isNewSkill) {
            actions.setSkill(DEFAULT_SKILL_FORM_VALUES)
            actions.resetSkillForm(DEFAULT_SKILL_FORM_VALUES)
        } else {
            actions.loadSkill()
        }
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        '/llm-analytics/skills/:name': (_, __, ___, { method }) => {
            if (method === 'PUSH' && values.isNewSkill) {
                actions.setSkill(DEFAULT_SKILL_FORM_VALUES)
                actions.resetSkillForm(DEFAULT_SKILL_FORM_VALUES)
                return
            }

            if (method === 'PUSH' && !values.isNewSkill) {
                actions.loadSkill()
            }
        },
    })),
])
