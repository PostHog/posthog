import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { beforeUnload, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { objectsEqual } from 'lib/utils/objects'
import { emailTemplaterLogic } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { EDITOR_MODE_PARAM, EDITOR_MODE_VALUE } from 'scenes/max/aiFirstCreate/aiFirstMode'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    messagingTemplatesMakeTransactionalCreate,
    messagingTemplatesPartialUpdate,
} from 'products/messaging/frontend/generated/api'
import type { MessageTemplateContentApi } from 'products/messaging/frontend/generated/api.schemas'
import { resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

import {
    senderAddressError,
    senderFrom,
    senderIntegrationFor,
} from '../../../../frontend/src/scenes/hog-functions/email-templater/emailSenderFields'
import type { EmailTemplate } from '../../../../frontend/src/scenes/hog-functions/email-templater/types'
import type { HogFunctionType, ResourceEditedEvent, UserBasicType } from '../../../../frontend/src/types'
import type { IntegrationType } from '../../../../frontend/src/types'
import { opensRunLogs, withoutRunLogFilters } from '../Transactional/runLogLinks'
import { workflowLogic } from '../Workflows/workflowLogic'
import { NEW_TEMPLATE } from './constants'
import { newTemplateAgentLogic } from './newTemplateAgentLogic'
import { omitNullDesign } from './omitNullDesign'
import { TemplateSection, templateLibraryUrl, templateSectionFor, templateUrlInSection } from './templateSection'
import { MessageTemplate } from './types'

export type TransactionalTemplateTab = 'design' | 'impact' | 'metrics' | 'sends' | 'runs' | 'versions' | 'api'

const TEMPLATE_PAGE_ROUTES = [
    '/transactional/library/templates/:id',
    '/workflows/library/templates/:id',
    '/broadcasts/library/templates/:id',
]
// pinned: values of the `tab` URL search param - renaming breaks shared links
const TRANSACTIONAL_TEMPLATE_TABS: TransactionalTemplateTab[] = [
    'design',
    'impact',
    'metrics',
    'sends',
    'runs',
    'versions',
    'api',
]

type TemplateContent = MessageTemplate['content']

// By template id. Outside the logic, because a write outlives the page it started on.
const pendingTagWrites = new Map<string, Promise<string[] | undefined>>()

function warnAboutPendingTags(event: BeforeUnloadEvent): void {
    event.preventDefault()
}

/** Content as the server stores it: without unset keys or a null design, which the form may still hold. */
function asStored(content: TemplateContent | null): TemplateContent | null {
    return content ? JSON.parse(JSON.stringify({ ...content, email: omitNullDesign(content.email) })) : null
}

/** The form edits the draft when there is one. The draft field stays off the form value, so a publish never sends it. */
function splitDraft(template: MessageTemplate): {
    form: MessageTemplate
    draft: TemplateContent | null
    published: TemplateContent
} {
    const { draft_content, ...form } = template
    const draft = (draft_content as TemplateContent | null | undefined) ?? null
    return { form: draft ? { ...form, content: draft } : form, draft, published: template.content }
}

function isOlderThanLoaded(
    incomingUpdatedAt: string | null | undefined,
    loadedUpdatedAt: string | null | undefined
): boolean {
    return !!loadedUpdatedAt && !!incomingUpdatedAt && dayjs(incomingUpdatedAt).isBefore(dayjs(loadedUpdatedAt))
}

function preserveNewerSettings(incoming: MessageTemplate, loaded: MessageTemplate): MessageTemplate {
    if (isOlderThanLoaded(incoming.updated_at, loaded.updated_at)) {
        return {
            ...incoming,
            sensitive: loaded.sensitive,
            click_tracking_enabled: loaded.click_tracking_enabled,
            updated_at: loaded.updated_at,
        }
    }
    return incoming
}

async function flushCanvasAndCheckDirty(props: MessageTemplateLogicProps): Promise<{
    stillMounted: boolean
    canvasUnsaved: boolean
}> {
    const templater = emailTemplaterLogic.findMounted()
    if (templater) {
        await templater.asyncActions.flushPendingDesignEdit()
        if (!messageTemplateLogic.isMounted(props)) {
            return { stillMounted: false, canvasUnsaved: false }
        }
        return { stillMounted: true, canvasUnsaved: templater.isMounted() && templater.values.latestEditUnsaved }
    }
    return { stillMounted: messageTemplateLogic.isMounted(props), canvasUnsaved: false }
}

interface OwnSettingSnapshot {
    updatedAt: string
    name: string
    description: string
    transactionalHogFlowId: string | null
    publishedContent: TemplateContent | null
    serverDraft: TemplateContent | null
}

interface MessageTemplateCache {
    formWhenSaving?: MessageTemplate
    ownSettingSnapshot?: OwnSettingSnapshot | null
    tagWriteGeneration?: number
}

interface ApplySettingUpdateResult {
    applied: boolean
    ownSettingSnapshot: OwnSettingSnapshot | null
}

function matchesOwnSettingSnapshot(
    snapshot: OwnSettingSnapshot | null | undefined,
    loadedUpdatedAt: string | null | undefined,
    expected: {
        name: string
        description?: string
        transactional_hog_flow_id?: string | null
        publishedContent: TemplateContent | null
        serverDraft: TemplateContent | null
    }
): boolean {
    return (
        !!snapshot &&
        !!loadedUpdatedAt &&
        snapshot.updatedAt === loadedUpdatedAt &&
        snapshot.name === expected.name &&
        snapshot.description === (expected.description ?? '') &&
        snapshot.transactionalHogFlowId === (expected.transactional_hog_flow_id ?? null) &&
        objectsEqual(snapshot.publishedContent, expected.publishedContent) &&
        objectsEqual(snapshot.serverDraft, expected.serverDraft)
    )
}

function applySettingUpdate(
    updated: Awaited<ReturnType<typeof messagingTemplatesPartialUpdate>>,
    values: {
        originalTemplate: MessageTemplate
        template: MessageTemplate
        publishedContent: TemplateContent | null
        serverDraft: TemplateContent | null
        hasUnsavedChanges: boolean
        externallyEdited: boolean
        templateChanged: boolean
        isDiscardingDraft: boolean
        isTemplateSubmitting: boolean
        savedTemplateLoading: boolean
        templateLoading: boolean
    },
    actions: {
        setDraftState: (draft: TemplateContent | null, published: TemplateContent) => void
        setOriginalTemplate: (template: MessageTemplate) => void
        resetTemplate: (values?: MessageTemplate) => void
        setExternallyEdited: (externallyEdited: boolean) => void
        setTemplateValues: (
            values: Partial<Pick<MessageTemplate, 'sensitive' | 'click_tracking_enabled' | 'updated_at' | 'tags'>>
        ) => void
    },
    options: {
        canvasUnsaved: boolean
        hasConcurrentTagWrite: boolean
    }
): ApplySettingUpdateResult {
    const loadedUpdatedAt = values.originalTemplate.updated_at
    if (loadedUpdatedAt && updated.updated_at && dayjs(updated.updated_at).isBefore(dayjs(loadedUpdatedAt))) {
        return { applied: false, ownSettingSnapshot: null }
    }

    const {
        form: serverForm,
        draft: serverDraft,
        published: serverPublished,
    } = splitDraft(updated as unknown as MessageTemplate)
    const serverTagsChanged =
        !options.hasConcurrentTagWrite && !objectsEqual(serverForm.tags ?? [], values.originalTemplate.tags ?? [])
    const hasExternalChanges =
        serverForm.name !== values.originalTemplate.name ||
        (serverForm.description ?? '') !== (values.originalTemplate.description ?? '') ||
        (serverForm.transactional_hog_flow_id ?? null) !==
            (values.originalTemplate.transactional_hog_flow_id ?? null) ||
        !objectsEqual(serverPublished ?? null, values.publishedContent) ||
        !objectsEqual(serverDraft, values.serverDraft)

    const settingChanges: Partial<
        Pick<MessageTemplate, 'sensitive' | 'click_tracking_enabled' | 'updated_at' | 'tags'>
    > = {
        sensitive: updated.sensitive,
        click_tracking_enabled: updated.click_tracking_enabled,
        updated_at: updated.updated_at,
        ...(serverTagsChanged ? { tags: serverForm.tags } : {}),
    }

    const snapshot: OwnSettingSnapshot = {
        updatedAt: updated.updated_at,
        name: serverForm.name,
        description: serverForm.description ?? '',
        transactionalHogFlowId: serverForm.transactional_hog_flow_id ?? null,
        publishedContent: serverPublished ?? null,
        serverDraft,
    }

    if (
        values.isDiscardingDraft ||
        values.templateLoading ||
        values.savedTemplateLoading ||
        values.isTemplateSubmitting
    ) {
        actions.setOriginalTemplate({ ...values.originalTemplate, ...settingChanges })
        if (values.templateChanged) {
            actions.setTemplateValues(settingChanges)
        } else {
            actions.resetTemplate({ ...values.template, ...settingChanges })
        }
        return { applied: true, ownSettingSnapshot: snapshot }
    }

    const hasLocalUnsaved = values.hasUnsavedChanges || options.canvasUnsaved
    if (hasExternalChanges && !hasLocalUnsaved && !values.externallyEdited) {
        const reconciledServerForm = options.hasConcurrentTagWrite
            ? { ...serverForm, tags: values.template.tags }
            : serverForm
        actions.setDraftState(serverDraft, serverPublished)
        actions.setOriginalTemplate(reconciledServerForm)
        actions.resetTemplate(reconciledServerForm)
        return { applied: true, ownSettingSnapshot: null }
    }

    if (hasExternalChanges) {
        actions.setExternallyEdited(true)
    }

    actions.setOriginalTemplate({ ...values.originalTemplate, ...settingChanges })
    if (values.templateChanged) {
        actions.setTemplateValues(settingChanges)
    } else {
        actions.resetTemplate({ ...values.template, ...settingChanges })
    }
    return { applied: true, ownSettingSnapshot: hasExternalChanges ? null : snapshot }
}

export interface MessageTemplateLogicProps {
    id: string
    messageId?: string | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface messageTemplateLogicValues {
    integrations: IntegrationType[] | null // integrationsLogic
    aiComposerAvailable: boolean // newTemplateAgentLogic
    currentTeamIdStrict: number | string // teamLogic
    deferredExternalEdit: ResourceEditedEvent | null
    draftOutOfDate: boolean
    draftsEnabled: boolean
    externallyEdited: boolean
    failedTagSaves: number
    hasDraft: boolean
    hasUnsavedChanges: boolean
    isDiscardingDraft: boolean
    isMakingTransactional: boolean
    isReconcilingPublish: boolean
    isSavingClickTracking: boolean
    isSavingDraft: boolean
    isSavingSensitive: boolean
    isSyncingExternalEdit: boolean
    isTemplateSubmitting: boolean
    isTemplateValid: boolean
    isTransactional: boolean
    listUrl: string
    logicProps: MessageTemplateLogicProps
    message: any
    messageLoading: boolean
    originalTemplate: MessageTemplate
    publishedContent: TemplateContent | null
    savedDraft: TemplateContent | null
    savedTemplate: MessageTemplate | null
    savedTemplateLoading: boolean
    section: TemplateSection
    serverDraft: TemplateContent | null
    showTemplateErrors: boolean
    template: MessageTemplate
    templateAllErrors: Record<string, any>
    templateChanged: boolean
    templateErrors: DeepPartialMap<
        {
            click_tracking_enabled?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['click_tracking_enabled']
            content: {
                email: EmailTemplate
                templating: 'hog' | 'liquid'
            }
            created_at: string | null
            created_by: UserBasicType | null
            description: string
            draft_content?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['draft_content']
            id: string
            name: string
            sensitive?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['sensitive']
            tags?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['tags']
            transactional_hog_flow_id?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['transactional_hog_flow_id']
            updated_at: string | null
        },
        ValidationErrorType
    >
    templateHasErrors: boolean
    templateLoading: boolean
    templateManualErrors: Record<string, any>
    templatePickerOpen: boolean
    templateTouched: boolean
    templateTouches: Record<string, boolean>
    templateValidationErrors: DeepPartialMap<
        {
            click_tracking_enabled?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['click_tracking_enabled']
            content: {
                email: EmailTemplate
                templating: 'hog' | 'liquid'
            }
            created_at: string | null
            created_by: UserBasicType | null
            description: string
            draft_content?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['draft_content']
            id: string
            name: string
            sensitive?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['sensitive']
            tags?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['tags']
            transactional_hog_flow_id?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['transactional_hog_flow_id']
            updated_at: string | null
        },
        ValidationErrorType
    >
    transactionalHogFlowId: string | null
    transactionalTab: TransactionalTemplateTab
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface messageTemplateLogicActions {
    resourceEdited: (event: ResourceEditedEvent) => {
        event: ResourceEditedEvent
    } // resourceEditedLogic
    autoSaveDraft: () => {
        value: true
    }
    confirmDiscardDraft: () => {
        value: true
    }
    deleteTemplate: () => {
        value: true
    }
    discardDraft: () => {
        value: true
    }
    discardDraftDone: () => {
        value: true
    }
    duplicateTemplate: () => {
        value: true
    }
    keepMyTemplateVersion: () => {
        value: true
    }
    loadMessage: () => any
    loadMessageFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMessageSuccess: (
        message: HogFunctionType | null,
        payload?: any
    ) => {
        message: HogFunctionType | null
        payload?: any
    }
    loadTemplate: () => any
    loadTemplateFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadTemplateSuccess: (
        template: MessageTemplate,
        payload?: any
    ) => {
        template: MessageTemplate
        payload?: any
    }
    makeTransactional: () => {
        value: true
    }
    makeTransactionalDone: (hogFlowId: string | null) => {
        hogFlowId: string | null
    }
    replayDeferredExternalEdit: () => {
        value: true
    }
    resetTemplate: (values?: {
        click_tracking_enabled?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['click_tracking_enabled']
        content: {
            email: EmailTemplate
            templating: 'hog' | 'liquid'
        }
        created_at: string | null
        created_by: UserBasicType | null
        description: string
        draft_content?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['draft_content']
        id: string
        name: string
        sensitive?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['sensitive']
        tags?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['tags']
        transactional_hog_flow_id?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['transactional_hog_flow_id']
        updated_at: string | null
    }) => {
        values?: {
            click_tracking_enabled?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['click_tracking_enabled']
            content: {
                email: EmailTemplate
                templating: 'hog' | 'liquid'
            }
            created_at: string | null
            created_by: UserBasicType | null
            description: string
            draft_content?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['draft_content']
            id: string
            name: string
            sensitive?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['sensitive']
            tags?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['tags']
            transactional_hog_flow_id?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['transactional_hog_flow_id']
            updated_at: string | null
        }
    }
    saveDraft: () => {
        value: true
    }
    saveDraftDone: (
        draft: TemplateContent,
        updatedAt: string,
        serverDraft?: TemplateContent | null
    ) => {
        draft: {
            email: EmailTemplate
            templating: 'hog' | 'liquid'
        }
        serverDraft:
            | {
                  email: EmailTemplate
                  templating: 'hog' | 'liquid'
              }
            | null
            | undefined
        updatedAt: string
    }
    saveDraftFailed: () => {
        value: true
    }
    saveTags: (tags: string[]) => {
        tags: string[]
    }
    saveTagsFailed: () => {
        value: true
    }
    saveTemplate: (template: MessageTemplate) => MessageTemplate
    saveTemplateFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    saveTemplateSuccess: (
        savedTemplate: MessageTemplate,
        payload?: MessageTemplate
    ) => {
        savedTemplate: MessageTemplate
        payload?: MessageTemplate
    }
    setClickTrackingEnabled: (clickTrackingEnabled: boolean) => {
        clickTrackingEnabled: boolean
    }
    setClickTrackingEnabledDone: () => {
        value: true
    }
    setDeferredExternalEdit: (event: ResourceEditedEvent | null) => {
        event: ResourceEditedEvent | null
    }
    setDraftState: (
        draft: TemplateContent | null,
        published: TemplateContent
    ) => {
        draft: {
            email: EmailTemplate
            templating: 'hog' | 'liquid'
        } | null
        published: {
            email: EmailTemplate
            templating: 'hog' | 'liquid'
        }
    }
    setExternallyEdited: (externallyEdited: boolean) => {
        externallyEdited: boolean
    }
    setOriginalTemplate: (template: MessageTemplate) => {
        template: MessageTemplate
    }
    setReconcilingPublish: (reconciling: boolean) => {
        reconciling: boolean
    }
    setSensitive: (sensitive: boolean) => {
        sensitive: boolean
    }
    setSensitiveDone: () => {
        value: true
    }
    setSyncingExternalEdit: (syncing: boolean) => {
        syncing: boolean
    }
    setTemplate: (template: MessageTemplate) => {
        template: MessageTemplate
    }
    setTemplateManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setTemplatePickerOpen: (open: boolean) => {
        open: boolean
    }
    setTemplateValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setTemplateValues: (
        values: DeepPartial<{
            click_tracking_enabled?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['click_tracking_enabled']
            content: {
                email: EmailTemplate
                templating: 'hog' | 'liquid'
            }
            created_at: string | null
            created_by: UserBasicType | null
            description: string
            draft_content?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['draft_content']
            id: string
            name: string
            sensitive?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['sensitive']
            tags?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['tags']
            transactional_hog_flow_id?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['transactional_hog_flow_id']
            updated_at: string | null
        }>
    ) => {
        values: DeepPartial<{
            click_tracking_enabled?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['click_tracking_enabled']
            content: {
                email: EmailTemplate
                templating: 'hog' | 'liquid'
            }
            created_at: string | null
            created_by: UserBasicType | null
            description: string
            draft_content?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['draft_content']
            id: string
            name: string
            sensitive?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['sensitive']
            tags?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['tags']
            transactional_hog_flow_id?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['transactional_hog_flow_id']
            updated_at: string | null
        }>
    }
    setTransactionalTab: (tab: TransactionalTemplateTab) => {
        tab: TransactionalTemplateTab
    }
    submitTemplate: () => {
        value: boolean
    }
    submitTemplateFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitTemplateRequest: (template: {
        click_tracking_enabled?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['click_tracking_enabled']
        content: {
            email: EmailTemplate
            templating: 'hog' | 'liquid'
        }
        created_at: string | null
        created_by: UserBasicType | null
        description: string
        draft_content?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['draft_content']
        id: string
        name: string
        sensitive?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['sensitive']
        tags?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['tags']
        transactional_hog_flow_id?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['transactional_hog_flow_id']
        updated_at: string | null
    }) => {
        template: {
            click_tracking_enabled?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['click_tracking_enabled']
            content: {
                email: EmailTemplate
                templating: 'hog' | 'liquid'
            }
            created_at: string | null
            created_by: UserBasicType | null
            description: string
            draft_content?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['draft_content']
            id: string
            name: string
            sensitive?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['sensitive']
            tags?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['tags']
            transactional_hog_flow_id?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['transactional_hog_flow_id']
            updated_at: string | null
        }
    }
    submitTemplateSuccess: (template: {
        click_tracking_enabled?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['click_tracking_enabled']
        content: {
            email: EmailTemplate
            templating: 'hog' | 'liquid'
        }
        created_at: string | null
        created_by: UserBasicType | null
        description: string
        draft_content?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['draft_content']
        id: string
        name: string
        sensitive?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['sensitive']
        tags?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['tags']
        transactional_hog_flow_id?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['transactional_hog_flow_id']
        updated_at: string | null
    }) => {
        template: {
            click_tracking_enabled?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['click_tracking_enabled']
            content: {
                email: EmailTemplate
                templating: 'hog' | 'liquid'
            }
            created_at: string | null
            created_by: UserBasicType | null
            description: string
            draft_content?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['draft_content']
            id: string
            name: string
            sensitive?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['sensitive']
            tags?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['tags']
            transactional_hog_flow_id?: import('products/messaging/frontend/generated/api.schemas').MessageTemplateApi['transactional_hog_flow_id']
            updated_at: string | null
        }
    }
    syncExternalEdit: () => {
        value: true
    }
    templateEditedElsewhere: (event: ResourceEditedEvent) => {
        event: ResourceEditedEvent
    }
    touchTemplateField: (key: string) => {
        key: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface messageTemplateLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        logicProps: (arg: MessageTemplateLogicProps) => MessageTemplateLogicProps
        transactionalHogFlowId: (originalTemplate: MessageTemplate) => string | null
        isTransactional: (transactionalHogFlowId: string | null) => boolean
        section: (location: { hash: string; pathname: string; search: string }) => TemplateSection
        listUrl: (isTransactional: boolean, section: TemplateSection) => string
        draftsEnabled: (transactionalHogFlowId: string | null) => boolean
        hasDraft: (
            savedDraft: {
                email: EmailTemplate
                templating: 'hog' | 'liquid'
            } | null
        ) => boolean
        draftOutOfDate: (
            template: MessageTemplate,
            savedDraft: {
                email: EmailTemplate
                templating: 'hog' | 'liquid'
            } | null,
            publishedContent: {
                email: EmailTemplate
                templating: 'hog' | 'liquid'
            } | null
        ) => boolean
        hasUnsavedChanges: (
            draftsEnabled: boolean,
            templateChanged: boolean,
            template: MessageTemplate,
            originalTemplate: MessageTemplate,
            draftOutOfDate: boolean
        ) => boolean
    }
}

export type messageTemplateLogicType = MakeLogicType<
    messageTemplateLogicValues,
    messageTemplateLogicActions,
    MessageTemplateLogicProps,
    messageTemplateLogicMeta
>

export const messageTemplateLogic = kea<messageTemplateLogicType>([
    path(['products', 'workflows', 'frontend', 'messageTemplateLogic']),
    props({} as MessageTemplateLogicProps),
    key(({ id }) => id ?? 'new'),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamIdStrict'],
            newTemplateAgentLogic,
            ['aiComposerAvailable'],
            integrationsLogic,
            ['integrations'],
        ],
        actions: [resourceEditedLogic, ['resourceEdited']],
    })),
    actions({
        setTemplate: (template: MessageTemplate) => ({ template }),
        setOriginalTemplate: (template: MessageTemplate) => ({ template }),
        duplicateTemplate: true,
        deleteTemplate: true,
        setTemplatePickerOpen: (open: boolean) => ({ open }),
        saveTags: (tags: string[]) => ({ tags }),
        saveTagsFailed: true,
        templateEditedElsewhere: (event: ResourceEditedEvent) => ({ event }),
        setDeferredExternalEdit: (event: ResourceEditedEvent | null) => ({ event }),
        replayDeferredExternalEdit: true,
        syncExternalEdit: true,
        keepMyTemplateVersion: true,
        setExternallyEdited: (externallyEdited: boolean) => ({ externallyEdited }),
        setReconcilingPublish: (reconciling: boolean) => ({ reconciling }),
        setSyncingExternalEdit: (syncing: boolean) => ({ syncing }),
        makeTransactional: true,
        makeTransactionalDone: (hogFlowId: string | null) => ({ hogFlowId }),
        setSensitive: (sensitive: boolean) => ({ sensitive }),
        setSensitiveDone: true,
        setClickTrackingEnabled: (clickTrackingEnabled: boolean) => ({ clickTrackingEnabled }),
        setClickTrackingEnabledDone: true,
        setTransactionalTab: (tab: TransactionalTemplateTab) => ({ tab }),
        setDraftState: (draft: TemplateContent | null, published: TemplateContent) => ({ draft, published }),
        autoSaveDraft: true,
        saveDraft: true,
        saveDraftDone: (draft: TemplateContent, updatedAt: string, serverDraft?: TemplateContent | null) => ({
            draft,
            updatedAt,
            serverDraft,
        }),
        saveDraftFailed: true,
        discardDraft: true,
        confirmDiscardDraft: true,
        discardDraftDone: true,
    }),
    selectors({
        logicProps: [
            () => [(_, props: MessageTemplateLogicProps) => props],
            (props: MessageTemplateLogicProps): MessageTemplateLogicProps => props,
        ],
    }),
    forms(({ actions, values }) => ({
        template: {
            defaults: {
                ...NEW_TEMPLATE,
            },
            errors: (template: MessageTemplate) => ({
                name: !template.name ? 'Name is required' : undefined,
                content: {
                    email: {
                        subject: !template.content.email.subject ? 'Subject is required' : undefined,
                        from: {
                            email:
                                senderAddressError(
                                    senderFrom(template.content.email).email,
                                    senderIntegrationFor(template.content.email, values.integrations)
                                ) ?? undefined,
                        },
                    },
                },
            }),
            submit: async (template) => {
                if (values.isReconcilingPublish || values.isDiscardingDraft) {
                    return
                }
                actions.saveTemplate(template)
            },
        },
    })),
    reducers({
        template: [
            { ...NEW_TEMPLATE } as MessageTemplate,
            {
                setTemplate: (_, { template }) => template,
            },
        ],
        originalTemplate: [
            { ...NEW_TEMPLATE } as MessageTemplate,
            {
                setOriginalTemplate: (_, { template }) => template,
                loadTemplateSuccess: (_, { template }) => {
                    return template
                },
            },
        ],
        isMakingTransactional: [
            false,
            {
                makeTransactional: () => true,
                makeTransactionalDone: () => false,
            },
        ],
        isSavingSensitive: [
            false,
            {
                setSensitive: () => true,
                setSensitiveDone: () => false,
            },
        ],
        isSavingClickTracking: [
            false,
            {
                setClickTrackingEnabled: () => true,
                setClickTrackingEnabledDone: () => false,
            },
        ],
        // The draft as last saved, and the content sends use. Both come from the server.
        savedDraft: [
            null as TemplateContent | null,
            {
                setDraftState: (_, { draft }) => draft,
                saveDraftDone: (_, { draft }) => draft,
            },
        ],
        serverDraft: [
            null as TemplateContent | null,
            {
                setDraftState: (_, { draft }) => draft,
                saveDraftDone: (_, { draft, serverDraft }) => (serverDraft !== undefined ? serverDraft : draft),
            },
        ],
        publishedContent: [
            null as TemplateContent | null,
            {
                setDraftState: (_, { published }) => published ?? null,
            },
        ],
        isSavingDraft: [
            false,
            {
                saveDraft: () => true,
                saveDraftDone: () => false,
                saveDraftFailed: () => false,
            },
        ],
        isDiscardingDraft: [
            false,
            {
                confirmDiscardDraft: () => true,
                discardDraftDone: () => false,
            },
        ],
        transactionalTab: [
            'design' as TransactionalTemplateTab,
            {
                setTransactionalTab: (_, { tab }) => tab,
            },
        ],
        failedTagSaves: [
            0,
            {
                saveTagsFailed: (count) => count + 1,
            },
        ],
        templatePickerOpen: [
            false,
            {
                setTemplatePickerOpen: (_, { open }) => open,
            },
        ],
        // Another channel (the PostHog AI agent, the API, another tab) saved this template while the form
        // holds unsaved edits. The banner lets the person choose which version wins.
        externallyEdited: [
            false,
            {
                setExternallyEdited: (_, { externallyEdited }) => externallyEdited,
            },
        ],
        isSyncingExternalEdit: [
            false,
            {
                setSyncingExternalEdit: (_, { syncing }) => syncing,
            },
        ],
        isReconcilingPublish: [
            false,
            {
                setReconcilingPublish: (_, { reconciling }) => reconciling,
            },
        ],
        // An edit event that arrived while our own save or load was in flight. Replayed once it settles.
        // The newest stamp wins, so our own echo cannot displace an external edit that arrived before it.
        deferredExternalEdit: [
            null as ResourceEditedEvent | null,
            {
                setDeferredExternalEdit: (state, { event }) =>
                    !event || !state || dayjs(event.updated_at).isAfter(dayjs(state.updated_at)) ? event : state,
            },
        ],
    }),
    selectors({
        // The saved state decides it: an unsaved template can't be transactional yet.
        transactionalHogFlowId: [
            (s) => [s.originalTemplate],
            (originalTemplate: MessageTemplate): string | null => originalTemplate.transactional_hog_flow_id ?? null,
        ],
        isTransactional: [
            (s) => [s.transactionalHogFlowId],
            (transactionalHogFlowId: string | null): boolean => !!transactionalHogFlowId,
        ],
        // The nav section the page was opened under. Links from the page stay in it.
        section: [
            () => [router.selectors.location],
            (location: { pathname: string }): TemplateSection => templateSectionFor(location.pathname),
        ],
        // The list a person returns to: transactional emails live in their own section.
        listUrl: [
            (s) => [s.isTransactional, s.section],
            (isTransactional: boolean, section: TemplateSection): string =>
                isTransactional ? urls.transactional() : templateLibraryUrl(section),
        ],
        // Sends use a transactional template's content, so its edits save as a draft until they are published.
        draftsEnabled: [
            (s) => [s.transactionalHogFlowId],
            (transactionalHogFlowId: string | null): boolean => !!transactionalHogFlowId,
        ],
        hasDraft: [
            (s) => [s.savedDraft],
            (
                savedDraft: {
                    email: EmailTemplate
                    templating: 'hog' | 'liquid'
                } | null
            ): boolean => savedDraft !== null,
        ],
        draftOutOfDate: [
            (s) => [s.template, s.savedDraft, s.publishedContent],
            (
                template: MessageTemplate,
                savedDraft: {
                    email: EmailTemplate
                    templating: 'hog' | 'liquid'
                } | null,
                publishedContent: {
                    email: EmailTemplate
                    templating: 'hog' | 'liquid'
                } | null
            ): boolean => !objectsEqual(template.content, savedDraft ?? publishedContent),
        ],
        hasUnsavedChanges: [
            (s) => [s.draftsEnabled, s.templateChanged, s.template, s.originalTemplate, s.draftOutOfDate],
            (
                draftsEnabled: boolean,
                templateChanged: boolean,
                template: MessageTemplate,
                originalTemplate: MessageTemplate,
                draftOutOfDate: boolean
            ): boolean =>
                draftsEnabled
                    ? template.name !== originalTemplate.name ||
                      template.description !== originalTemplate.description ||
                      draftOutOfDate
                    : templateChanged,
        ],
    }),
    loaders(({ props, actions }) => ({
        template: {
            loadTemplate: async () => {
                if (!props.id || props.id === 'new') {
                    return {
                        ...NEW_TEMPLATE,
                    } as MessageTemplate
                }

                // The person can come back before the tags they left with are saved.
                await pendingTagWrites.get(props.id)
                const { form, draft, published } = splitDraft(await api.messaging.getTemplate(props.id))
                actions.setDraftState(draft, published)
                return form
            },
        },
        // Apart from `template`, so a save neither reads as a load nor replaces what is typed while it runs.
        savedTemplate: {
            __default: null as MessageTemplate | null,
            saveTemplate: async (template: MessageTemplate) => {
                // Saving the content publishes it, and the server clears the draft. The sensitive setting
                // and the tags each save on their own, so a publish never sends them and can't undo a
                // change made in another tab since this one loaded the template.
                const payload = template.content?.email
                    ? { ...template, content: { ...template.content, email: omitNullDesign(template.content.email) } }
                    : template
                const {
                    sensitive: _sensitive,
                    click_tracking_enabled: _clickTrackingEnabled,
                    tags: _tags,
                    ...content
                } = payload
                const saved =
                    template.id === 'new'
                        ? await api.messaging.createTemplate(payload)
                        : await api.messaging.updateTemplate(template.id, content)
                const { form, draft, published } = splitDraft(saved)
                actions.setDraftState(draft, published)
                return form
            },
        },
        message: {
            loadMessage: async () => {
                if (!props.messageId) {
                    return null
                }
                return await api.hogFunctions.get(props.messageId)
            },
        },
    })),
    listeners(({ actions, props, values, cache }) => ({
        setTransactionalTab: ({ tab }) => {
            const { tab: _shownTab, ...searchParams } = router.values.searchParams
            const kept = tab === 'sends' ? withoutRunLogFilters(searchParams) : searchParams
            const next = tab === 'design' ? kept : { ...kept, tab }
            if (!objectsEqual(next, { ...router.values.searchParams })) {
                router.actions.replace(router.values.location.pathname, next, router.values.hashParams)
            }
        },
        resourceEdited: ({ event }) => {
            if (event.resource_type === 'MessageTemplate' && event.resource_id === props.id) {
                actions.templateEditedElsewhere(event)
            }
        },
        templateEditedElsewhere: async ({ event }) => {
            // The echo of our own save can arrive before its response. Parked until the flight settles,
            // it then compares equal to the loaded stamp and is dropped.
            const parkedOrStale = (): boolean => {
                if (
                    values.templateLoading ||
                    values.savedTemplateLoading ||
                    values.isReconcilingPublish ||
                    values.isMakingTransactional ||
                    values.isSavingSensitive ||
                    values.isSavingClickTracking ||
                    values.isSavingDraft ||
                    values.isDiscardingDraft
                ) {
                    actions.setDeferredExternalEdit(event)
                    return true
                }
                const loadedUpdatedAt = values.originalTemplate.updated_at
                return !loadedUpdatedAt || !dayjs(event.updated_at).isAfter(dayjs(loadedUpdatedAt))
            }
            if (parkedOrStale()) {
                return
            }
            // The canvas hands its edits over late, so the form can look clean while it holds one.
            const templater = emailTemplaterLogic.findMounted()
            if (templater) {
                await templater.asyncActions.flushPendingDesignEdit()
                if (!messageTemplateLogic.isMounted(props) || parkedOrStale()) {
                    return
                }
            }
            if (values.hasUnsavedChanges || (templater?.isMounted() && templater.values.latestEditUnsaved)) {
                actions.setExternallyEdited(true)
            } else {
                actions.syncExternalEdit()
            }
        },
        replayDeferredExternalEdit: () => {
            const event = values.deferredExternalEdit
            if (event) {
                actions.setDeferredExternalEdit(null)
                actions.templateEditedElsewhere(event)
            }
        },
        setDraftState: ({ draft }) => {
            cache.serverDraft = draft
        },
        syncExternalEdit: () => {
            // A draft only holds what the person typed, so a reload that finds it gone must not take the text with it.
            // Reload from the banner is the person choosing the other version, so it takes nothing along.
            // The server's own copy of the draft, which it stores normalized, so a reload compares like with like.
            const serverDraft = cache.serverDraft !== undefined ? cache.serverDraft : values.savedDraft
            cache.beforeSync = values.externallyEdited ? null : { draft: serverDraft, content: values.template.content }
            actions.setSyncingExternalEdit(true)
            actions.loadTemplate()
        },
        keepMyTemplateVersion: () => {
            actions.setExternallyEdited(false)
            actions.autoSaveDraft()
        },
        setTemplateValue: () => actions.autoSaveDraft(),
        saveTags: async ({ tags }) => {
            // An unsaved template has no row yet, so its tags ride the create.
            if (!props.id || props.id === 'new') {
                actions.setTemplateValue('tags', tags)
                return
            }
            const { id } = props
            const showTags = (shown: string[] | undefined): void => {
                actions.setTemplate({ ...values.template, tags: shown })
                actions.setOriginalTemplate({ ...values.originalTemplate, tags: shown })
            }
            // One write at a time, so an older one can't land last. Without a breakpoint, leaving the page
            // can't cancel a tag that already looks saved.
            const writeBefore: Promise<string[] | undefined> =
                pendingTagWrites.get(id) ?? Promise.resolve(values.originalTemplate.tags)
            const cacheState = cache as MessageTemplateCache
            let failed = false
            const write: Promise<string[] | undefined> = writeBefore.then(async (saved) => {
                // A newer edit already holds these tags.
                if (pendingTagWrites.get(id) !== write) {
                    return saved
                }
                try {
                    // Tags are metadata: they apply live and must not publish a transactional template's draft,
                    // which a full form save would.
                    const savedTags = (await api.messaging.updateTemplate(id, { tags })).tags
                    cacheState.tagWriteGeneration = (cacheState.tagWriteGeneration ?? 0) + 1
                    return savedTags
                } catch (error: any) {
                    failed = true
                    if (pendingTagWrites.get(id) === write) {
                        lemonToast.error(`Failed to save tags: ${error?.detail || error?.message || 'Unknown error'}`)
                    }
                    return saved
                }
            })
            pendingTagWrites.set(id, write)
            window.addEventListener('beforeunload', warnAboutPendingTags)
            // Shown at once, so the next tag adds to this one instead of replacing it.
            showTags(tags)
            const saved = await write
            if (pendingTagWrites.get(id) !== write) {
                return
            }
            pendingTagWrites.delete(id)
            if (!pendingTagWrites.size) {
                window.removeEventListener('beforeunload', warnAboutPendingTags)
            }
            if (messageTemplateLogic.isMounted(props)) {
                showTags(saved)
                if (failed) {
                    actions.saveTagsFailed()
                }
            }
        },
        setTemplateValues: () => actions.autoSaveDraft(),
        autoSaveDraft: async (_, breakpoint) => {
            if (!values.draftsEnabled) {
                return
            }
            await breakpoint(1500)
            // A save in flight starts the next one when it lands, so edits made meanwhile are not lost.
            // While the edited-elsewhere banner is up, a save would overwrite the other edit before the person chooses.
            if (
                !values.draftOutOfDate ||
                values.externallyEdited ||
                values.isReconcilingPublish ||
                values.templateLoading ||
                values.isTemplateSubmitting ||
                values.savedTemplateLoading ||
                values.isSavingDraft ||
                values.isDiscardingDraft ||
                values.isSavingSensitive ||
                values.isSavingClickTracking
            ) {
                return
            }
            actions.saveDraft()
        },
        saveDraft: async () => {
            const content = values.template.content
            try {
                const updated = await messagingTemplatesPartialUpdate(String(values.currentTeamIdStrict), props.id, {
                    // The form type still allows the legacy 'hog' templating, which templates never use.
                    draft_content: { ...content, email: omitNullDesign(content.email) } as MessageTemplateContentApi,
                })
                const serverDraft = (updated.draft_content as TemplateContent | null | undefined) ?? null
                cache.serverDraft = serverDraft
                actions.saveDraftDone(content, updated.updated_at, serverDraft)
            } catch {
                actions.saveDraftFailed()
                lemonToast.error("Couldn't save your draft. Your changes are still in the editor.")
            }
        },
        saveDraftDone: ({ updatedAt }) => {
            ;(cache as MessageTemplateCache).ownSettingSnapshot = null
            // The echo of this save then matches the loaded stamp and is not read as an edit from elsewhere.
            actions.setOriginalTemplate({ ...values.originalTemplate, updated_at: updatedAt })
            actions.replayDeferredExternalEdit()
            actions.autoSaveDraft()
        },
        saveDraftFailed: () => {
            actions.replayDeferredExternalEdit()
        },
        discardDraft: () => {
            LemonDialog.open({
                title: 'Discard your draft?',
                description: 'This deletes your unpublished changes. The live email stays as it is.',
                primaryButton: {
                    children: 'Discard draft',
                    status: 'danger',
                    onClick: () => actions.confirmDiscardDraft(),
                },
                secondaryButton: { children: 'Cancel' },
            })
        },
        confirmDiscardDraft: async (_, breakpoint) => {
            // Wait for any in-flight draft, publish, or setting save so an older response cannot bring the draft back.
            while (
                values.isSavingDraft ||
                values.savedTemplateLoading ||
                values.isReconcilingPublish ||
                values.isSavingSensitive ||
                values.isSavingClickTracking
            ) {
                await breakpoint(100)
            }
            try {
                const cacheState = cache as MessageTemplateCache
                const updated = await messagingTemplatesPartialUpdate(String(values.currentTeamIdStrict), props.id, {
                    draft_content: null,
                })
                const { stillMounted, canvasUnsaved } = await flushCanvasAndCheckDirty(props)
                if (!stillMounted) {
                    return
                }
                const {
                    form: discardForm,
                    draft: discardDraft,
                    published,
                } = splitDraft(updated as unknown as MessageTemplate)
                const discardIsOlder = isOlderThanLoaded(updated.updated_at, values.originalTemplate.updated_at)
                const newerIsOnlyOwnSetting =
                    discardIsOlder &&
                    !values.externallyEdited &&
                    matchesOwnSettingSnapshot(cacheState.ownSettingSnapshot, values.originalTemplate.updated_at, {
                        name: discardForm.name,
                        description: discardForm.description,
                        transactional_hog_flow_id: discardForm.transactional_hog_flow_id,
                        publishedContent: published ?? null,
                        serverDraft: discardDraft,
                    })
                if (discardIsOlder && !newerIsOnlyOwnSetting) {
                    if (values.hasUnsavedChanges || canvasUnsaved) {
                        actions.setExternallyEdited(true)
                    } else {
                        actions.syncExternalEdit()
                    }
                } else {
                    const nextOriginal = preserveNewerSettings(
                        {
                            ...values.originalTemplate,
                            content: published,
                            sensitive: updated.sensitive,
                            click_tracking_enabled: updated.click_tracking_enabled,
                            updated_at: updated.updated_at,
                        },
                        values.originalTemplate
                    )
                    const discardChanges = {
                        content: published,
                        sensitive: nextOriginal.sensitive,
                        click_tracking_enabled: nextOriginal.click_tracking_enabled,
                        updated_at: nextOriginal.updated_at,
                    }
                    cacheState.ownSettingSnapshot = null
                    actions.setDraftState(null, published)
                    actions.setOriginalTemplate(nextOriginal)
                    actions.resetTemplate({ ...values.template, ...discardChanges })
                }
            } catch {
                lemonToast.error("Couldn't discard your draft. Try again.")
            }
            actions.discardDraftDone()
            actions.replayDeferredExternalEdit()
        },
        makeTransactional: async () => {
            try {
                const updated = await messagingTemplatesMakeTransactionalCreate(
                    String(values.currentTeamIdStrict),
                    props.id,
                    {}
                )
                // Only these fields changed. Merging them in keeps edits made while this ran.
                const changes = {
                    transactional_hog_flow_id: updated.transactional_hog_flow_id ?? null,
                    updated_at: updated.updated_at,
                }
                // Conversion stores the sender it sends from on the template, so the editor shows it.
                const from = updated.content?.email?.from as EmailTemplate['from'] | undefined
                const withSender = (template: MessageTemplate): MessageTemplate =>
                    from
                        ? {
                              ...template,
                              ...changes,
                              content: { ...template?.content, email: { ...template?.content?.email, from } },
                          }
                        : { ...template, ...changes }
                actions.setOriginalTemplate(withSender(values.originalTemplate))
                if (values.templateChanged) {
                    actions.setTemplateValues(changes)
                    if (from) {
                        actions.setTemplateValue('content.email.from', from)
                    }
                } else {
                    // Resetting moves the form's baseline too, so the form doesn't read as edited.
                    actions.resetTemplate(withSender(values.template))
                }
                actions.makeTransactionalDone(updated.transactional_hog_flow_id ?? null)
                actions.replayDeferredExternalEdit()
                lemonToast.success('Template is now transactional. You can send it over the API.')
            } catch (error: any) {
                actions.makeTransactionalDone(null)
                actions.replayDeferredExternalEdit()
                lemonToast.error(error?.detail ?? 'Could not make the template transactional.')
            }
        },
        setSensitive: async ({ sensitive }, breakpoint) => {
            // Wait for an in-flight draft or publish save so the loaded snapshot matches the server before reconciling.
            while (
                values.isSavingDraft ||
                values.templateLoading ||
                values.savedTemplateLoading ||
                values.isReconcilingPublish
            ) {
                await breakpoint(100)
            }
            try {
                const cacheState = cache as MessageTemplateCache
                const tagGenerationBefore = cacheState.tagWriteGeneration ?? 0
                // Saved on its own, so it applies to sends at once and leaves any content draft untouched.
                const updated = await messagingTemplatesPartialUpdate(String(values.currentTeamIdStrict), props.id, {
                    sensitive,
                })
                const { stillMounted, canvasUnsaved } = await flushCanvasAndCheckDirty(props)
                if (!stillMounted) {
                    return
                }
                const result = applySettingUpdate(updated, values, actions, {
                    canvasUnsaved,
                    hasConcurrentTagWrite:
                        pendingTagWrites.has(props.id) || (cacheState.tagWriteGeneration ?? 0) !== tagGenerationBefore,
                })
                if (result.applied) {
                    cacheState.ownSettingSnapshot = result.ownSettingSnapshot
                }
                posthog.capture('email template sensitive changed', { template_id: props.id, sensitive })
            } catch (error: any) {
                lemonToast.error(error?.detail ?? "Couldn't change the setting. Try again.")
            }
            actions.setSensitiveDone()
            actions.replayDeferredExternalEdit()
            actions.autoSaveDraft()
        },
        setClickTrackingEnabled: async ({ clickTrackingEnabled }, breakpoint) => {
            while (
                values.isSavingDraft ||
                values.templateLoading ||
                values.savedTemplateLoading ||
                values.isReconcilingPublish
            ) {
                await breakpoint(100)
            }
            try {
                const cacheState = cache as MessageTemplateCache
                const tagGenerationBefore = cacheState.tagWriteGeneration ?? 0
                const updated = await messagingTemplatesPartialUpdate(String(values.currentTeamIdStrict), props.id, {
                    click_tracking_enabled: clickTrackingEnabled ? true : null,
                })
                const { stillMounted, canvasUnsaved } = await flushCanvasAndCheckDirty(props)
                if (!stillMounted) {
                    return
                }
                const result = applySettingUpdate(updated, values, actions, {
                    canvasUnsaved,
                    hasConcurrentTagWrite:
                        pendingTagWrites.has(props.id) || (cacheState.tagWriteGeneration ?? 0) !== tagGenerationBefore,
                })
                if (result.applied) {
                    cacheState.ownSettingSnapshot = result.ownSettingSnapshot
                    if (updated.sensitive) {
                        posthog.capture('email template click tracking changed', {
                            template_id: props.id,
                            click_tracking_enabled: updated.click_tracking_enabled === true,
                        })
                    } else {
                        lemonToast.info(
                            'Sensitive data protection was turned off elsewhere, so link click tracking is on by default.'
                        )
                    }
                }
            } catch (error: any) {
                lemonToast.error(error?.detail ?? "Couldn't change the setting. Try again.")
            }
            actions.setClickTrackingEnabledDone()
            actions.replayDeferredExternalEdit()
            actions.autoSaveDraft()
        },
        loadTemplateFailure: () => {
            // The form is still the stale copy. The banner keeps the conflict visible and offers the retry.
            if (values.isSyncingExternalEdit) {
                actions.setSyncingExternalEdit(false)
                actions.setExternallyEdited(true)
            }
        },
        loadTemplateSuccess: ({ template }) => {
            ;(cache as MessageTemplateCache).ownSettingSnapshot = null
            if (values.isSyncingExternalEdit) {
                const beforeSync = cache.beforeSync as {
                    draft: TemplateContent | null
                    content: TemplateContent
                } | null
                cache.beforeSync = null
                const draftLostElsewhere =
                    !!beforeSync?.draft &&
                    !objectsEqual(asStored(beforeSync.draft), asStored(values.savedDraft ?? values.publishedContent))
                // The server copy replaces the form. A Reload from the banner discards the local edits on purpose.
                // A draft replaced or removed elsewhere held the person's typing, so it stays and the banner asks.
                actions.resetTemplate(
                    draftLostElsewhere && beforeSync ? { ...template, content: beforeSync.content } : template
                )
                actions.setSyncingExternalEdit(false)
                actions.setExternallyEdited(draftLostElsewhere)
            }
            actions.replayDeferredExternalEdit()
        },
        submitTemplateFailure: () => {
            const errors = values.templateAllErrors
            if (errors?.name) {
                lemonToast.error('Name is required')
            } else if (errors?.content?.email?.subject) {
                lemonToast.error('Subject is required')
            } else if (typeof errors?.content?.email?.from === 'object' && errors.content.email.from.email) {
                lemonToast.error(errors.content.email.from.email)
            }
        },
        saveTemplate: () => {
            ;(cache as MessageTemplateCache).formWhenSaving = values.template
        },
        saveTemplateFailure: ({ errorObject }) => {
            actions.replayDeferredExternalEdit()
            // A 404 means the template no longer resolves for this environment - it was soft-deleted,
            // or it belongs to a different environment than the one currently selected.
            if (errorObject?.status === 404) {
                lemonToast.error('This template no longer exists in this environment. It may have been deleted.', {
                    button: {
                        label: 'Back to library',
                        action: () => router.actions.push(urls.workflows('library')),
                    },
                })
                return
            }
            lemonToast.error('Failed to save template. Please try again.')
            actions.autoSaveDraft()
        },
        saveTemplateSuccess: async ({ savedTemplate: template }) => {
            const cacheState = cache as MessageTemplateCache
            const sent: MessageTemplate = cacheState.formWhenSaving ?? values.template
            const publishedFromSave = values.publishedContent
            const draftFromSave = values.serverDraft
            const computeTypedMeanwhile = (
                current: MessageTemplate
            ): Partial<Pick<MessageTemplate, 'name' | 'description' | 'content'>> =>
                props.id === 'new'
                    ? {}
                    : {
                          ...(current.name !== sent.name ? { name: current.name } : {}),
                          ...(current.description !== sent.description ? { description: current.description } : {}),
                          ...(objectsEqual(current.content, sent.content) ? {} : { content: current.content }),
                      }
            lemonToast.success(
                props.id === 'new' ? 'Template created' : values.draftsEnabled ? 'Published' : 'Template saved'
            )

            const initialPublishIsOlder = isOlderThanLoaded(template.updated_at, values.originalTemplate.updated_at)
            const initialNewerIsOnlyOwnSetting =
                initialPublishIsOlder &&
                !values.externallyEdited &&
                matchesOwnSettingSnapshot(cacheState.ownSettingSnapshot, values.originalTemplate.updated_at, {
                    name: template.name,
                    description: template.description,
                    transactional_hog_flow_id: template.transactional_hog_flow_id,
                    publishedContent: publishedFromSave,
                    serverDraft: draftFromSave,
                })

            let canvasUnsaved = false
            let markedReconciling = false
            try {
                if (initialPublishIsOlder && !initialNewerIsOnlyOwnSetting) {
                    actions.setReconcilingPublish(true)
                    markedReconciling = true
                    const flush = await flushCanvasAndCheckDirty(props)
                    if (!flush.stillMounted) {
                        return
                    }
                    canvasUnsaved = flush.canvasUnsaved
                }

                const current = values.template
                const typedMeanwhile = computeTypedMeanwhile(current)
                // Tags save on their own, so the answer to this save can hold older ones.
                const tagsChanged = current.tags !== sent.tags || pendingTagWrites.has(template.id)
                const saved = props.id !== 'new' && tagsChanged ? { ...template, tags: current.tags } : template
                // Clear the unsaved-changes state before navigating so the beforeUnload guard
                // does not intercept the post-save redirect.
                const publishIsOlder = isOlderThanLoaded(saved.updated_at, values.originalTemplate.updated_at)
                const newerIsOnlyOwnSetting =
                    publishIsOlder &&
                    !values.externallyEdited &&
                    matchesOwnSettingSnapshot(cacheState.ownSettingSnapshot, values.originalTemplate.updated_at, {
                        name: saved.name,
                        description: saved.description,
                        transactional_hog_flow_id: saved.transactional_hog_flow_id,
                        publishedContent: publishedFromSave,
                        serverDraft: draftFromSave,
                    })
                const needsExternalReconcile = publishIsOlder && !newerIsOnlyOwnSetting
                const hasLocalEdits = Object.keys(typedMeanwhile).length > 0 || canvasUnsaved
                const reconciled = preserveNewerSettings(saved, values.originalTemplate)
                if (!publishIsOlder) {
                    cacheState.ownSettingSnapshot = null
                }
                actions.setExternallyEdited(needsExternalReconcile && hasLocalEdits)
                actions.resetTemplate(reconciled)
                actions.setOriginalTemplate(reconciled)
                if (values.transactionalHogFlowId) {
                    // The save wrote a new workflow version, and nothing else tells the bound workflow tabs.
                    workflowLogic.findMounted({ id: values.transactionalHogFlowId })?.actions.loadWorkflow()
                }
                if (props.id === 'new') {
                    router.actions.push(urls.workflows('library'))
                } else if (template.id) {
                    router.actions.replace(templateUrlInSection(template.id, values.section))
                }
                // After the navigation, which would otherwise ask to discard them.
                if (Object.keys(typedMeanwhile).length > 0) {
                    actions.setTemplateValues(typedMeanwhile)
                }
                if (needsExternalReconcile && !hasLocalEdits) {
                    actions.syncExternalEdit()
                }
            } finally {
                if (markedReconciling && messageTemplateLogic.isMounted(props)) {
                    actions.setReconcilingPublish(false)
                }
            }
            actions.replayDeferredExternalEdit()
        },
        loadMessageSuccess: async ({ message }) => {
            if (!message) {
                return
            }
            actions.setTemplateValues({
                name: message.name,
                description: message.description,
                content: {
                    email: message.inputs?.email?.value,
                },
            })
        },
        duplicateTemplate: async () => {
            if (values.hasUnsavedChanges) {
                lemonToast.error('Please save your changes before duplicating')
                return
            }
            const template = values.template
            try {
                const duplicatedTemplate = await api.messaging.createTemplate({
                    name: `${template.name} (copy)`,
                    description: template.description,
                    content: template.content,
                })
                lemonToast.success('Template duplicated successfully')
                router.actions.push(templateUrlInSection(duplicatedTemplate.id, values.section))
            } catch {
                lemonToast.error('Failed to duplicate template')
            }
        },
        deleteTemplate: async () => {
            const template = values.template
            if (!template || template.id === 'new') {
                return
            }
            await deleteWithUndo({
                endpoint: `environments/${values.currentTeamIdStrict}/messaging_templates`,
                object: {
                    id: template.id,
                    name: template.name,
                },
                callback: (undo) => {
                    if (!undo) {
                        router.actions.push(values.listUrl)
                    }
                },
            })
        },
    })),
    urlToAction(({ actions, props, values }) => {
        const readTab = ({ id }: { id?: string }, searchParams: Record<string, any>): void => {
            const tab = opensRunLogs(searchParams)
                ? 'runs'
                : (TRANSACTIONAL_TEMPLATE_TABS.find((known) => known === searchParams.tab) ?? 'design')
            if (id === props.id && tab !== values.transactionalTab) {
                actions.setTransactionalTab(tab)
            }
        }
        return {
            [urls.workflowsLibraryTemplateNew()]: (_, searchParams) => {
                if (props.id === 'new' && !props.messageId && searchParams[EDITOR_MODE_PARAM] === EDITOR_MODE_VALUE) {
                    actions.setTemplatePickerOpen(true)
                }
            },
            ...Object.fromEntries(TEMPLATE_PAGE_ROUTES.map((route) => [route, readTab])),
        }
    }),
    afterMount(({ props, actions, values }) => {
        if (props.id !== 'new') {
            actions.loadTemplate()
        }

        if (props.messageId) {
            actions.loadMessage()
        } else {
            // If we've previously loaded a message, reset the template to the default
            actions.resetTemplate(NEW_TEMPLATE)
        }

        // A fresh template starts from the picker: blank, or one of the existing templates. The AI composer
        // is its own starting point, so the picker waits for the escape hatch there.
        if (props.id === 'new' && !props.messageId && !values.aiComposerAvailable) {
            actions.setTemplatePickerOpen(true)
        }
    }),
    beforeUnload(({ values, actions }) => ({
        // Guards both new and existing templates - a brand-new template only exists in form
        // state until "Create" is pressed, so leaving without saving would discard it entirely.
        enabled: (newLocation) => {
            if (!values.hasUnsavedChanges) {
                return false
            }
            // Allow same-path changes (e.g. query params) through without warning.
            if (newLocation && newLocation.pathname === router.values.location.pathname) {
                return false
            }
            return true
        },
        message: 'Leave template?\nChanges you made will be discarded.',
        onConfirm: () => actions.resetTemplate(values.originalTemplate),
    })),
])
