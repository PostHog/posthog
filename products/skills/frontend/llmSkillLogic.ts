import {
    MakeLogicType,
    actions,
    afterMount,
    defaults,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'

import { ApiConfig, ApiError } from '~/lib/api'
import { isAccessDeniedError } from '~/lib/api-error'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { urls } from '~/scenes/urls'
import { Breadcrumb } from '~/types'

import { getApiErrorDetail, openDiscardChangesDialog } from 'products/ai_observability/frontend/prompts/utils'
import {
    llmSkillsCreate,
    llmSkillsNameArchiveCreate,
    llmSkillsNameFilesRetrieve,
    llmSkillsNamePartialUpdate,
    llmSkillsResolveNameRetrieve,
} from 'products/skills/frontend/generated/api'
import type {
    LLMSkillApi,
    LLMSkillFileApi,
    LLMSkillFileInputApi,
    LLMSkillListApi,
    LLMSkillVersionSummaryApi,
    UserBasicApi,
} from 'products/skills/frontend/generated/api.schemas'

import { exportAndDownloadSkill, llmSkillsLogic, LLM_SKILLS_FORCE_RELOAD_PARAM } from './llmSkillsLogic'
import {
    SKILL_DESCRIPTION_MAX_LENGTH,
    SKILL_FILE_MAX_BYTES,
    SKILL_FILE_MAX_COUNT,
    validateSkillName,
} from './skillConstants'
import type { SkillFileUpload } from './skillFileUpload'

export enum SkillMode {
    View = 'view',
    Edit = 'edit',
}

export interface SkillLogicProps {
    skillName: string | 'new'
    mode?: SkillMode
    selectedVersion?: number | null
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

// Values must stay within COMMON_CONTENT_TYPES in LLMSkillScene, so the content-type
// select can display whatever gets inferred here.
const CONTENT_TYPE_BY_EXTENSION: Record<string, string> = {
    md: 'text/markdown',
    markdown: 'text/markdown',
    py: 'text/x-python',
    sh: 'text/x-shellscript',
    bash: 'text/x-shellscript',
    zsh: 'text/x-shellscript',
    json: 'application/json',
    yaml: 'text/yaml',
    yml: 'text/yaml',
    js: 'text/javascript',
    mjs: 'text/javascript',
    cjs: 'text/javascript',
    jsx: 'text/javascript',
    ts: 'text/typescript',
    tsx: 'text/typescript',
}

function inferFileContentType(fileName: string): string {
    const extension = fileName.toLowerCase().split('.').pop() ?? ''
    return CONTENT_TYPE_BY_EXTENSION[extension] ?? 'text/plain'
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
const STALE_SKILL_ERROR_MESSAGE =
    'This skill changed while you were editing it. Your edits are preserved. Review the latest version and publish again.'

export interface PublishConflict {
    latestVersion: number | null
}

export interface SkillLoadError {
    /** Undefined when the request never reached the server: a `NetworkError` carries no status. */
    status: number | undefined
    code: string | null
}

// Sorted by path so a reorder that ends up byte-identical on the server is not presented as a change.
function sortSkillFilesByPath(files: SkillFormFileValues[]): SkillFormFileValues[] {
    return [...files].sort((a, b) => a.path.localeCompare(b.path))
}

function normalizeSkillFormForCompare(form: SkillFormValues): SkillFormValues {
    return {
        ...form,
        files: sortSkillFilesByPath(form.files),
    }
}

function areSkillFilesEqual(a: SkillFormFileValues[], b: SkillFormFileValues[]): boolean {
    return JSON.stringify(sortSkillFilesByPath(a)) === JSON.stringify(sortSkillFilesByPath(b))
}

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

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface llmSkillLogicValues {
    breadcrumbs: Breadcrumb[]
    canCompareVersions: boolean
    canLoadMoreVersions: boolean
    compareSkill: LLMSkillApi | null
    compareSkillLoading: boolean
    compareVersion: number | null
    compareVersionOptions: Array<{
        label: string
        value: number
    }>
    downloadingZip: boolean
    fileContentsLoading: boolean
    hasSkillLoadError: boolean
    isDiffVisible: boolean
    isEditMode: boolean
    isHistoricalVersion: boolean
    isNewSkill: boolean
    isOutlineExpanded: boolean
    isPublishReviewOpen: boolean
    isSkillAccessDenied: boolean
    isSkillFormDirty: boolean
    isSkillFormSubmitting: boolean
    isSkillFormValid: boolean
    isSkillMissing: boolean
    isViewMode: boolean
    mode: SkillMode
    nextVersion: number | null
    ownerDraft: string[]
    ownerDraftChanged: boolean
    ownersEditing: boolean
    publishConflict: PublishConflict | null
    savingOwners: boolean
    selectedVersion: number | null
    shouldDisplaySkeleton: boolean
    showSkillFormErrors: boolean
    skill: ResolvedLLMSkill | SkillFormValues | null
    skillFetched: boolean
    skillForm: SkillFormValues
    skillFormAllErrors: Record<string, any>
    skillFormBaseline: SkillFormValues | null
    skillFormChanged: boolean
    skillFormErrors: DeepPartialMap<SkillFormValues, ValidationErrorType>
    skillFormHasErrors: boolean
    skillFormManualErrors: Record<string, any>
    skillFormTouched: boolean
    skillFormTouches: Record<string, boolean>
    skillFormValidationErrors: DeepPartialMap<SkillFormValues, ValidationErrorType>
    skillLoadError: SkillLoadError | null
    skillLoading: boolean
    skillName: string
    skillOwners: readonly UserBasicApi[]
    versionDescription: string
    versions: LLMSkillVersionSummaryApi[]
    versionsLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface llmSkillLogicActions {
    addUploadedFiles: (files: SkillFileUpload[]) => {
        files: SkillFileUpload[]
    }
    cancelEditing: () => {
        value: true
    }
    closeOwnersEditor: () => {
        value: true
    }
    closePublishReview: () => {
        value: true
    }
    deleteSkill: () => {
        value: true
    }
    downloadSkill: () => {
        value: true
    }
    loadCompareSkill: (version: number) => number
    loadCompareSkillFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCompareSkillSuccess: (
        compareSkill: LLMSkillApi,
        payload?: number
    ) => {
        compareSkill: LLMSkillApi
        payload?: number
    }
    loadFileContents: () => {
        value: true
    }
    loadMoreVersions: () => {
        value: true
    }
    loadSkill: () => any
    loadSkillFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSkillSuccess: (
        skill: ResolvedLLMSkill,
        payload?: any
    ) => {
        skill: ResolvedLLMSkill
        payload?: any
    }
    openOwnersEditor: () => {
        value: true
    }
    openPublishReview: () => {
        value: true
    }
    requestPublish: () => {
        value: true
    }
    resetSkillForm: (values?: SkillFormValues) => {
        values?: SkillFormValues
    }
    saveOwners: (ownerUuids: string[]) => {
        ownerUuids: string[]
    }
    setCompareVersion: (compareVersion: number | null) => {
        compareVersion: number | null
    }
    setDownloadingZip: (downloadingZip: boolean) => {
        downloadingZip: boolean
    }
    setFileContentsLoading: (loading: boolean) => {
        loading: boolean
    }
    setMode: (mode: SkillMode) => {
        mode: SkillMode
    }
    setOwnerDraft: (ownerUuids: string[]) => {
        ownerUuids: string[]
    }
    setPublishConflict: (publishConflict: PublishConflict | null) => {
        publishConflict: PublishConflict | null
    }
    setSavingOwners: (saving: boolean) => {
        saving: boolean
    }
    setSkill: (skill: ResolvedLLMSkill | SkillFormValues) => {
        skill: ResolvedLLMSkill | SkillFormValues
    }
    setSkillFormBaseline: (baseline: SkillFormValues | null) => {
        baseline: SkillFormValues | null
    }
    setSkillFormManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setSkillFormValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setSkillFormValues: (values: DeepPartial<SkillFormValues>) => {
        values: DeepPartial<SkillFormValues>
    }
    setVersionDescription: (versionDescription: string) => {
        versionDescription: string
    }
    setVersionsLoading: (versionsLoading: boolean) => {
        versionsLoading: boolean
    }
    submitSkillForm: () => {
        value: boolean
    }
    submitSkillFormFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitSkillFormRequest: (skillForm: SkillFormValues) => {
        skillForm: SkillFormValues
    }
    submitSkillFormSuccess: (skillForm: SkillFormValues) => {
        skillForm: SkillFormValues
    }
    toggleOutlineExpanded: () => {
        value: true
    }
    touchSkillFormField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface llmSkillLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        isNewSkill: (arg: any) => boolean
        skillName: (arg: SkillLogicProps) => string
        selectedVersion: (arg: SkillLogicProps) => number | null
        isSkillAccessDenied: (skillLoadError: SkillLoadError | null) => boolean
        hasSkillLoadError: (skillLoadError: SkillLoadError | null, isSkillAccessDenied: boolean) => boolean
        isSkillMissing: (
            skill: ResolvedLLMSkill | SkillFormValues | null,
            skillLoading: boolean,
            skillFetched: boolean,
            skillLoadError: SkillLoadError | null
        ) => boolean
        shouldDisplaySkeleton: (
            skill: ResolvedLLMSkill | SkillFormValues | null,
            skillLoading: boolean,
            skillFetched: boolean,
            isNewSkill: boolean
        ) => boolean
        isHistoricalVersion: (skill: ResolvedLLMSkill | SkillFormValues | null) => boolean
        breadcrumbs: (
            skill: ResolvedLLMSkill | SkillFormValues | null,
            skillName: string,
            searchParams: Record<string, any>
        ) => Breadcrumb[]
        isViewMode: (mode: SkillMode, arg: any) => boolean
        isEditMode: (mode: SkillMode, arg: any) => boolean
        isSkillFormDirty: (
            skillForm: SkillFormValues,
            skillFormBaseline: SkillFormValues | null,
            isNewSkill: boolean
        ) => boolean
        nextVersion: (skill: ResolvedLLMSkill | SkillFormValues | null) => number | null
        versions: (skill: ResolvedLLMSkill | SkillFormValues | null) => LLMSkillVersionSummaryApi[]
        canLoadMoreVersions: (skill: ResolvedLLMSkill | SkillFormValues | null) => boolean
        isDiffVisible: (compareVersion: number | null) => boolean
        canCompareVersions: (skill: ResolvedLLMSkill | SkillFormValues | null) => boolean
        compareVersionOptions: (
            skill: ResolvedLLMSkill | SkillFormValues | null,
            versions: LLMSkillVersionSummaryApi[]
        ) => Array<{
            label: string
            value: number
        }>
        skillOwners: (skill: ResolvedLLMSkill | SkillFormValues | null) => readonly UserBasicApi[]
        ownerDraftChanged: (ownerDraft: string[], skillOwners: readonly UserBasicApi[]) => boolean
    }
}

export type llmSkillLogicType = MakeLogicType<
    llmSkillLogicValues,
    llmSkillLogicActions,
    SkillLogicProps,
    llmSkillLogicMeta
>

export const llmSkillLogic = kea<llmSkillLogicType>([
    path(['scenes', 'skills', 'llmSkillLogic']),
    props({ skillName: 'new' } as SkillLogicProps),
    key(({ skillName, selectedVersion }) => `skill-${skillName}:${selectedVersion ?? 'latest'}`),
    actions({
        addUploadedFiles: (files: SkillFileUpload[]) => ({ files }),
        setSkill: (skill: ResolvedLLMSkill | SkillFormValues) => ({ skill }),
        deleteSkill: true,
        loadMoreVersions: true,
        setVersionsLoading: (versionsLoading: boolean) => ({ versionsLoading }),
        setMode: (mode: SkillMode) => ({ mode }),
        loadFileContents: true,
        setFileContentsLoading: (loading: boolean) => ({ loading }),
        toggleOutlineExpanded: true,
        setCompareVersion: (compareVersion: number | null) => ({ compareVersion }),
        downloadSkill: true,
        setDownloadingZip: (downloadingZip: boolean) => ({ downloadingZip }),
        cancelEditing: true,
        setPublishConflict: (publishConflict: PublishConflict | null) => ({ publishConflict }),
        requestPublish: true,
        openPublishReview: true,
        closePublishReview: true,
        setVersionDescription: (versionDescription: string) => ({ versionDescription }),
        setSkillFormBaseline: (baseline: SkillFormValues | null) => ({ baseline }),
        openOwnersEditor: true,
        closeOwnersEditor: true,
        setOwnerDraft: (ownerUuids: string[]) => ({ ownerUuids }),
        saveOwners: (ownerUuids: string[]) => ({ ownerUuids }),
        setSavingOwners: (saving: boolean) => ({ saving }),
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
        skillLoadError: [
            null as SkillLoadError | null,
            {
                loadSkill: () => null,
                loadSkillSuccess: () => null,
                loadSkillFailure: (_, { errorObject }) => ({
                    status: errorObject?.status,
                    code: errorObject?.code ?? null,
                }),
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
        compareVersion: [
            null as number | null,
            {
                setCompareVersion: (_, { compareVersion }) => compareVersion,
                loadSkillSuccess: () => null,
            },
        ],
        compareSkill: [
            null as LLMSkillApi | null,
            {
                setCompareVersion: () => null,
                loadSkillSuccess: () => null,
            },
        ],
        downloadingZip: [
            false,
            {
                setDownloadingZip: (_, { downloadingZip }) => downloadingZip,
            },
        ],
        publishConflict: [
            null as PublishConflict | null,
            {
                setPublishConflict: (_, { publishConflict }) => publishConflict,
                setMode: () => null,
                loadSkillSuccess: () => null,
            },
        ],
        isPublishReviewOpen: [
            false,
            {
                openPublishReview: () => true,
                closePublishReview: () => false,
                submitSkillFormSuccess: () => false,
                // A publish conflict (409) needs the editor visible again to show the banner
                setPublishConflict: () => false,
                setMode: () => false,
            },
        ],
        versionDescription: [
            '',
            {
                setVersionDescription: (_, { versionDescription }) => versionDescription,
                submitSkillFormSuccess: () => '',
                closePublishReview: () => '',
                setMode: () => '',
            },
        ],
        // What the editor started from, including lazily loaded file contents. The dirty check
        // compares the form against this, so a load that fills the form (loadFileContents) must
        // update it too or the fill itself would read as an edit.
        skillFormBaseline: [
            null as SkillFormValues | null,
            {
                loadSkillSuccess: (_, { skill }) => (isSkill(skill) ? getSkillFormDefaults(skill) : null),
                setSkillFormBaseline: (_, { baseline }) => baseline,
            },
        ],
        ownersEditing: [
            false,
            {
                openOwnersEditor: () => true,
                closeOwnersEditor: () => false,
                loadSkillSuccess: () => false,
            },
        ],
        ownerDraft: [
            [] as string[],
            {
                setOwnerDraft: (_, { ownerUuids }) => ownerUuids,
            },
        ],
        savingOwners: [
            false,
            {
                saveOwners: () => true,
                setSavingOwners: (_, { saving }) => saving,
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
        compareSkill: {
            __default: null as LLMSkillApi | null,
            loadCompareSkill: async (version: number) => {
                const resolved = await fetchResolvedSkill(props.skillName, { version, limit: 1 })
                return resolved as LLMSkillApi
            },
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

                    const formFiles: LLMSkillFileInputApi[] = formValues.files.map((f) => ({
                        path: f.path,
                        content: f.content,
                        content_type: f.content_type || undefined,
                    }))
                    // Send files only when the user changed them: omitting the key carries the
                    // current latest's files forward on the server, so an untouched file set can't
                    // clobber files a concurrent publish added, and publishing before the lazy file
                    // contents finish loading can't wipe content. An emptied set is a real change
                    // and goes through as [].
                    const baselineFiles = values.skillFormBaseline?.files
                    const filesChanged = !baselineFiles || !areSkillFilesEqual(formValues.files, baselineFiles)
                    const filesToSend: LLMSkillFileInputApi[] | undefined = filesChanged ? formFiles : undefined

                    if (isNew) {
                        const createResponse = await llmSkillsCreate(String(ApiConfig.getCurrentTeamId()), {
                            name: formValues.name,
                            description: formValues.description,
                            body: formValues.body,
                            license: formValues.license || undefined,
                            compatibility: formValues.compatibility || undefined,
                            files: formFiles.length > 0 ? formFiles : undefined,
                        })
                        savedSkill = { ...createResponse, files: [] }
                        llmSkillsLogic.findMounted()?.actions.loadSkills(false)
                        lemonToast.success('Skill created successfully')
                        router.actions.replace(urls.skill(savedSkill.name))
                    } else {
                        const currentSkill = values.skill

                        if (!isSkill(currentSkill)) {
                            throw new Error('Cannot publish skill version: skill data not loaded')
                        }

                        const versionDescription = values.versionDescription.trim()
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
                                ...(versionDescription ? { version_description: versionDescription } : {}),
                            }
                        )
                        llmSkillsLogic.findMounted()?.actions.loadSkills(false)
                        lemonToast.success(`Published v${savedSkill.version}`)

                        actions.setSkill({
                            ...savedSkill,
                            versions: [
                                {
                                    id: savedSkill.id,
                                    version: savedSkill.version,
                                    version_description: savedSkill.version_description ?? null,
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
                        actions.setSkillFormBaseline(getSkillFormDefaults(savedSkill))
                        router.actions.replace(urls.skill(props.skillName))

                        // PATCH already succeeded, so keep optimistic state even if follow-up read fails.
                        try {
                            const latest = await fetchResolvedSkill(props.skillName)
                            actions.setSkill(latest)
                            actions.setSkillFormValues(getSkillFormDefaults(latest))
                            actions.setSkillFormBaseline(getSkillFormDefaults(latest))
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
                        actions.setSkillFormBaseline(getSkillFormDefaults(savedSkill))
                    }
                } catch (error: unknown) {
                    if (error instanceof ApiError && error.status === 409) {
                        // Refresh the underlying skill so base_version advances, but keep the
                        // user's in-progress edits in the form. Never overwrite their work.
                        let latestVersion: number | null = null
                        try {
                            const latestSkill = await fetchResolvedSkill(props.skillName)
                            actions.setSkill(latestSkill)
                            latestVersion = latestSkill.latest_version ?? latestSkill.version
                        } catch {}

                        actions.setPublishConflict({ latestVersion })
                        lemonToast.error(STALE_SKILL_ERROR_MESSAGE)
                        throw error
                    }

                    lemonToast.error(getApiErrorDetail(error) || 'Failed to save skill')
                    throw error
                }
            },
        },
    })),

    selectors({
        isNewSkill: [() => [(_, props) => props], (props) => props.skillName === 'new'],

        skillName: [
            () => [(_: unknown, props: SkillLogicProps) => props],
            (props: SkillLogicProps): string => props.skillName,
        ],

        selectedVersion: [
            () => [(_: unknown, props: SkillLogicProps) => props],
            (props: SkillLogicProps): number | null => props.selectedVersion ?? null,
        ],

        isSkillAccessDenied: [
            (s) => [s.skillLoadError],
            (skillLoadError: SkillLoadError | null): boolean =>
                skillLoadError !== null && isAccessDeniedError(skillLoadError),
        ],

        hasSkillLoadError: [
            (s) => [s.skillLoadError, s.isSkillAccessDenied],
            (skillLoadError: SkillLoadError | null, isSkillAccessDenied: boolean): boolean =>
                skillLoadError !== null && skillLoadError.status !== 404 && !isSkillAccessDenied,
        ],

        // A 404 is the only failure that proves the skill isn't there. Every other failure (no access,
        // a server error, a request that never left the browser) leaves the question open, so it gets
        // its own state rather than telling the user a skill they may well own does not exist.
        isSkillMissing: [
            (s) => [s.skill, s.skillLoading, s.skillFetched, s.skillLoadError],
            (
                skill: ResolvedLLMSkill | SkillFormValues | null,
                skillLoading: boolean,
                skillFetched: boolean,
                skillLoadError: SkillLoadError | null
            ) =>
                skillFetched &&
                !skillLoading &&
                skill === null &&
                (skillLoadError === null || skillLoadError.status === 404),
        ],

        shouldDisplaySkeleton: [
            (s) => [s.skill, s.skillLoading, s.skillFetched, s.isNewSkill],
            (
                skill: ResolvedLLMSkill | SkillFormValues | null,
                skillLoading: boolean,
                skillFetched: boolean,
                isNewSkill: boolean
            ) => !isNewSkill && (!skillFetched || (skillLoading && skill === null)),
        ],

        isHistoricalVersion: [
            (s) => [s.skill],
            (skill: ResolvedLLMSkill | SkillFormValues | null) => (isSkill(skill) ? !skill.is_latest : false),
        ],

        breadcrumbs: [
            (s) => [s.skill, s.skillName, router.selectors.searchParams],
            (
                skill: LLMSkillApi | SkillFormValues | null,
                skillName: string,
                searchParams: Record<string, any>
            ): Breadcrumb[] => [
                {
                    name: 'Skills',
                    path: combineUrl(urls.skills(), searchParams).url,
                    key: 'Skills',
                },
                {
                    name:
                        skill && 'name' in skill
                            ? isSkill(skill)
                                ? `${skill.name} v${skill.version}`
                                : skill.name || 'New skill'
                            : skillName === 'new'
                              ? 'New skill'
                              : skillName,
                    key: 'Skill',
                },
            ],
        ],

        isViewMode: [
            (s) => [s.mode, (_, props) => props],
            (mode: SkillMode, props) => props.skillName !== 'new' && mode === SkillMode.View,
        ],

        isEditMode: [
            (s) => [s.mode, (_, props) => props],
            (mode: SkillMode, props) => props.skillName === 'new' || mode === SkillMode.Edit,
        ],

        isSkillFormDirty: [
            (s) => [s.skillForm, s.skillFormBaseline, s.isNewSkill],
            (skillForm: SkillFormValues, skillFormBaseline: SkillFormValues | null, isNewSkill: boolean): boolean => {
                if (isNewSkill) {
                    return (
                        !!skillForm.name.trim() ||
                        !!skillForm.description.trim() ||
                        !!skillForm.body.trim() ||
                        !!skillForm.license.trim() ||
                        !!skillForm.compatibility.trim() ||
                        skillForm.files.length > 0
                    )
                }
                if (!skillFormBaseline) {
                    return false
                }
                return (
                    JSON.stringify(normalizeSkillFormForCompare(skillForm)) !==
                    JSON.stringify(normalizeSkillFormForCompare(skillFormBaseline))
                )
            },
        ],

        nextVersion: [
            (s) => [s.skill],
            (skill: ResolvedLLMSkill | SkillFormValues | null): number | null =>
                isSkill(skill) ? (skill.latest_version ?? skill.version) + 1 : null,
        ],

        versions: [
            (s) => [s.skill],
            (skill: ResolvedLLMSkill | SkillFormValues | null): LLMSkillVersionSummaryApi[] =>
                isSkill(skill) ? skill.versions : [],
        ],

        canLoadMoreVersions: [
            (s) => [s.skill],
            (skill: ResolvedLLMSkill | SkillFormValues | null) => (isSkill(skill) ? skill.has_more : false),
        ],

        isDiffVisible: [(s) => [s.compareVersion], (compareVersion: number | null): boolean => compareVersion !== null],

        canCompareVersions: [
            (s) => [s.skill],
            (skill: ResolvedLLMSkill | SkillFormValues | null): boolean => isSkill(skill) && skill.version_count > 1,
        ],

        compareVersionOptions: [
            (s) => [s.skill, s.versions],
            (
                skill: ResolvedLLMSkill | SkillFormValues | null,
                versions: LLMSkillVersionSummaryApi[]
            ): Array<{ value: number; label: string }> => {
                if (!isSkill(skill)) {
                    return []
                }
                return versions
                    .filter((v) => v.version !== skill.version)
                    .map((v) => ({
                        value: v.version,
                        label: `v${v.version}${v.is_latest ? ' (latest)' : ''}`,
                    }))
            },
        ],

        skillOwners: [
            (s) => [s.skill],
            (skill: ResolvedLLMSkill | SkillFormValues | null): readonly UserBasicApi[] =>
                isSkill(skill) ? skill.owners : [],
        ],

        ownerDraftChanged: [
            (s) => [s.ownerDraft, s.skillOwners],
            (ownerDraft: string[], skillOwners: readonly UserBasicApi[]): boolean =>
                // Order is server-owned (seed-creator first), so only membership counts as a change.
                ownerDraft.length !== skillOwners.length ||
                ownerDraft.some((uuid) => !skillOwners.some((owner) => owner.uuid === uuid)),
        ],
    }),

    listeners(({ actions, props, values }) => ({
        addUploadedFiles: async ({ files }) => {
            const uploaded: SkillFormFileValues[] = []
            for (const { path, file } of files) {
                // Case-insensitive to match the backend's reserved-path validation
                if (path.toLowerCase() === 'skill.md') {
                    lemonToast.info(
                        "SKILL.md wasn't added as a bundled file. Its body belongs in the skill body field."
                    )
                    continue
                }
                if (file.size > SKILL_FILE_MAX_BYTES) {
                    lemonToast.error(`Couldn't add ${path}: files must be 1 MB or smaller`)
                    continue
                }
                // Strict decoding distinguishes real binary (invalid UTF-8, or NUL bytes) from
                // text that legitimately contains a U+FFFD replacement character.
                let content: string
                try {
                    content = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
                } catch {
                    lemonToast.error(`Couldn't add ${path}: only text files are supported`)
                    continue
                }
                if (content.includes('\u0000')) {
                    lemonToast.error(`Couldn't add ${path}: only text files are supported`)
                    continue
                }
                uploaded.push({ path, content, content_type: inferFileContentType(path) })
            }
            if (uploaded.length === 0) {
                return
            }
            const uploadedByPath = new Map(uploaded.map((f) => [f.path, f]))
            const merged = values.skillForm.files.map((existing) => {
                const replacement = uploadedByPath.get(existing.path)
                if (replacement) {
                    uploadedByPath.delete(existing.path)
                    return replacement
                }
                return existing
            })
            const combined = [...merged, ...uploadedByPath.values()]
            if (combined.length > SKILL_FILE_MAX_COUNT) {
                lemonToast.error(
                    `Some files weren't added: a skill can have at most ${SKILL_FILE_MAX_COUNT} bundled files`
                )
            }
            actions.setSkillFormValues({ files: combined.slice(0, SKILL_FILE_MAX_COUNT) })
        },

        downloadSkill: async () => {
            if (props.skillName === 'new') {
                return
            }
            actions.setDownloadingZip(true)
            try {
                await exportAndDownloadSkill(props.skillName)
            } catch (e) {
                console.error('Failed to export skill', e)
                const detail =
                    e !== null && typeof e === 'object' && 'detail' in e ? (e as { detail?: string }).detail : undefined
                lemonToast.error(detail || (e instanceof Error ? e.message : 'Failed to export skill'))
            } finally {
                actions.setDownloadingZip(false)
            }
        },

        deleteSkill: async () => {
            if (props.skillName !== 'new' && values.skill && isSkill(values.skill)) {
                try {
                    await llmSkillsNameArchiveCreate(String(ApiConfig.getCurrentTeamId()), values.skill.name)
                    lemonToast.info(`${values.skill.name || 'Skill'} has been archived.`)
                    llmSkillsLogic.findMounted()?.actions.loadSkills(false)
                    router.actions.replace(urls.skills(), {
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
                const files = fileContents.map((f) => ({
                    path: f.path,
                    content: f.content,
                    content_type: f.content_type || 'text/plain',
                }))
                actions.setSkillFormValues({ files })
                actions.setSkillFormBaseline(
                    values.skillFormBaseline
                        ? { ...values.skillFormBaseline, files }
                        : { ...getSkillFormDefaults(skill), files }
                )
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

        requestPublish: () => {
            // New skills publish directly (v1, nothing to diff against); an invalid form goes
            // through submit so kea-forms surfaces the validation errors.
            if (values.isNewSkill || !values.skillForm.body?.trim() || !values.skillForm.description?.trim()) {
                actions.submitSkillForm()
                return
            }
            actions.openPublishReview()
        },

        cancelEditing: () => {
            const exitEditMode = (): void => {
                if (values.isNewSkill) {
                    router.actions.push(urls.skills())
                    return
                }
                if (isSkill(values.skill)) {
                    actions.setSkillFormValues(values.skillFormBaseline ?? getSkillFormDefaults(values.skill))
                }
                actions.setMode(SkillMode.View)
            }

            if (values.isSkillFormDirty) {
                openDiscardChangesDialog(exitEditMode)
            } else {
                exitEditMode()
            }
        },

        loadSkillSuccess: ({ skill }) => {
            if (skill && isSkill(skill)) {
                actions.resetSkillForm()
                actions.setSkillFormValues(getSkillFormDefaults(skill))
            }
        },

        setCompareVersion: ({ compareVersion }) => {
            if (compareVersion !== null) {
                actions.loadCompareSkill(compareVersion)
            }
        },

        loadCompareSkillFailure: () => {
            lemonToast.error('Failed to load comparison version')
        },

        openOwnersEditor: () => {
            actions.setOwnerDraft(values.skillOwners.map((owner) => owner.uuid))
        },

        saveOwners: async ({ ownerUuids }) => {
            const currentSkill = values.skill
            if (props.skillName === 'new' || !isSkill(currentSkill)) {
                actions.setSavingOwners(false)
                return
            }
            try {
                // Owners-only PATCH: the backend replaces ownership without publishing a version.
                const updated = await llmSkillsNamePartialUpdate(
                    String(ApiConfig.getCurrentTeamId()),
                    props.skillName,
                    { owners: ownerUuids }
                )
                // Take only `owners` off the response: it describes the latest version, which is not
                // necessarily the version on screen. Ownership is version-independent, so it applies
                // to whichever version is shown.
                actions.setSkill({ ...currentSkill, owners: updated.owners })
                actions.closeOwnersEditor()
                llmSkillsLogic.findMounted()?.actions.loadSkills(false)
                lemonToast.success('Owners updated')
            } catch (error) {
                console.error('Failed to update skill owners', error)
                lemonToast.error(getApiErrorDetail(error) || "Couldn't update owners. Try again.")
            } finally {
                actions.setSavingOwners(false)
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
                    body_total_length: 0,
                    body_next_offset: null,
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

    afterMount(({ actions, values, cache }) => {
        if (values.isNewSkill) {
            actions.setSkill(DEFAULT_SKILL_FORM_VALUES)
            actions.resetSkillForm(DEFAULT_SKILL_FORM_VALUES)
        } else {
            actions.loadSkill()
        }

        // pauseOnPageHidden: false because closing a background tab must still warn about unsaved edits.
        cache.disposables.add(
            () => {
                const handler = (e: BeforeUnloadEvent): void => {
                    if (values.isEditMode && values.isSkillFormDirty && !values.isSkillFormSubmitting) {
                        e.preventDefault()
                        // Some engines only show the native dialog when returnValue is set
                        e.returnValue = ''
                    }
                }
                window.addEventListener('beforeunload', handler)
                return () => window.removeEventListener('beforeunload', handler)
            },
            'unsavedEditsGuard',
            { pauseOnPageHidden: false }
        )
    }),

    actionToUrl(({ props }) => ({
        // replace, not push: a push would re-trigger loadSkill via urlToAction and
        // its success handler would reset the form under the user's edits.
        setMode: ({ mode }) => {
            if (props.skillName === 'new') {
                return undefined
            }
            const { edit: _edit, ...searchParams } = router.values.searchParams
            return [
                router.values.location.pathname,
                mode === SkillMode.Edit ? { ...searchParams, edit: true } : searchParams,
                router.values.hashParams,
                { replace: true },
            ]
        },
    })),

    urlToAction(({ actions, values }) => ({
        '/skills/:name': (_, __, ___, { method }) => {
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
