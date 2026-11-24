import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type {
    CompleteActionApi,
    CreateHogApi,
    CreateHogScheduleApi,
    CreateHogTriggerApi,
    DecideActionApi,
    HogActionDTOApi,
    HogDTOApi,
    HogEventDTOApi,
    HogMessageDTOApi,
    HogReportDTOApi,
    HogRuleDTOApi,
    HogScheduleDTOApi,
    HogScheduleIdApi,
    HogTriggerDTOApi,
    HogTriggerIdApi,
    HogsMessagesRetrieveParams,
    HogsTriggersFireCreateBodyOne,
    HogsTriggersFireCreateBodyThree,
    HogsTriggersFireCreateBodyTwo,
    MessageContentApi,
    PatchedUpdateHogApi,
    ProposeActionApi,
    PublishReportApi,
    ReportFollowUpApi,
    ReportFollowUpResultApi,
    ReportIdApi,
    ReportVerdictApi,
    SetRuleApi,
    TellHogApi,
} from './api.schemas'

export const getHogsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hogs/`
}

/**
 * List the hogs you run, newest chat first, with unread counts.
 */
export const hogsList = async (projectId: string, options?: RequestInit): Promise<HogDTOApi[]> => {
    return apiMutator<HogDTOApi[]>(getHogsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getHogsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/hogs/`
}

/**
 * Persistent agents and the chat each one keeps with its owner.
 */
export const hogsCreate = async (
    projectId: string,
    createHogApi: CreateHogApi,
    options?: RequestInit
): Promise<HogDTOApi> => {
    return apiMutator<HogDTOApi>(getHogsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createHogApi),
    })
}

export const getHogsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/`
}

/**
 * Persistent agents and the chat each one keeps with its owner.
 */
export const hogsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<HogDTOApi> => {
    return apiMutator<HogDTOApi>(getHogsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogsPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/`
}

/**
 * Update a hog. A hog calls this to save its own responsibility, memory or status.
 */
export const hogsPartialUpdate = async (
    projectId: string,
    id: string,
    patchedUpdateHogApi?: PatchedUpdateHogApi,
    options?: RequestInit
): Promise<HogDTOApi> => {
    return apiMutator<HogDTOApi>(getHogsPartialUpdateUrl(projectId, id), {
        ...options,
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(patchedUpdateHogApi),
    })
}

export const getHogsDestroyUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/`
}

/**
 * Persistent agents and the chat each one keeps with its owner.
 */
export const hogsDestroy = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogsDestroyUrl(projectId, id), {
        ...options,
        method: 'DELETE',
    })
}

export const getHogsActionsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/actions/`
}

/**
 * List the actions a hog has proposed, newest first, with each one's status.
 */
export const hogsActionsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<HogActionDTOApi[]> => {
    return apiMutator<HogActionDTOApi[]>(getHogsActionsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogsActionsDecideCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/actions/decide/`
}

/**
 * Approve or deny an action a hog proposed. Approving wakes the hog to carry it out.
 */
export const hogsActionsDecideCreate = async (
    projectId: string,
    id: string,
    decideActionApi: DecideActionApi,
    options?: RequestInit
): Promise<HogActionDTOApi> => {
    return apiMutator<HogActionDTOApi>(getHogsActionsDecideCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(decideActionApi),
    })
}

export const getHogsActionsDoneCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/actions/done/`
}

/**
 * Record that the hog carried out an approved action.
 */
export const hogsActionsDoneCreate = async (
    projectId: string,
    id: string,
    completeActionApi: CompleteActionApi,
    options?: RequestInit
): Promise<HogActionDTOApi> => {
    return apiMutator<HogActionDTOApi>(getHogsActionsDoneCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(completeActionApi),
    })
}

export const getHogsActionsProposeCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/actions/propose/`
}

/**
 * Ask to do something outside PostHog. The owner's rules, or the owner, decide.
 */
export const hogsActionsProposeCreate = async (
    projectId: string,
    id: string,
    proposeActionApi: ProposeActionApi,
    options?: RequestInit
): Promise<HogActionDTOApi> => {
    return apiMutator<HogActionDTOApi>(getHogsActionsProposeCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(proposeActionApi),
    })
}

export const getHogsDoneCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/done/`
}

/**
 * Mark the hog as no longer working.
 */
export const hogsDoneCreate = async (projectId: string, id: string, options?: RequestInit): Promise<HogDTOApi> => {
    return apiMutator<HogDTOApi>(getHogsDoneCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getHogsMessagesRetrieveUrl = (projectId: string, id: string, params?: HogsMessagesRetrieveParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/hogs/${id}/messages/?${stringifiedParams}`
        : `/api/projects/${projectId}/hogs/${id}/messages/`
}

/**
 * List the chat with a hog, oldest first.
 */
export const hogsMessagesRetrieve = async (
    projectId: string,
    id: string,
    params?: HogsMessagesRetrieveParams,
    options?: RequestInit
): Promise<HogMessageDTOApi[]> => {
    return apiMutator<HogMessageDTOApi[]>(getHogsMessagesRetrieveUrl(projectId, id, params), {
        ...options,
        method: 'GET',
    })
}

export const getHogsReadCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/read/`
}

/**
 * Mark every message in the chat as read by the owner.
 */
export const hogsReadCreate = async (projectId: string, id: string, options?: RequestInit): Promise<void> => {
    return apiMutator<void>(getHogsReadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getHogsReportsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/reports/`
}

/**
 * List the reports a hog has published, open ones first.
 */
export const hogsReportsRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<HogReportDTOApi[]> => {
    return apiMutator<HogReportDTOApi[]>(getHogsReportsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogsReportsCreateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/reports/create/`
}

/**
 * Publish a report into the owner's chat, as the hog.
 */
export const hogsReportsCreateCreate = async (
    projectId: string,
    id: string,
    publishReportApi: PublishReportApi,
    options?: RequestInit
): Promise<HogReportDTOApi> => {
    return apiMutator<HogReportDTOApi>(getHogsReportsCreateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(publishReportApi),
    })
}

export const getHogsReportsFollowUpCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/reports/follow_up/`
}

/**
 * Wake the hog to implement or investigate one of its reports.
 */
export const hogsReportsFollowUpCreate = async (
    projectId: string,
    id: string,
    reportFollowUpApi: ReportFollowUpApi,
    options?: RequestInit
): Promise<ReportFollowUpResultApi> => {
    return apiMutator<ReportFollowUpResultApi>(getHogsReportsFollowUpCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reportFollowUpApi),
    })
}

export const getHogsReportsReadCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/reports/read/`
}

/**
 * Mark a report as opened by the owner.
 */
export const hogsReportsReadCreate = async (
    projectId: string,
    id: string,
    reportIdApi: ReportIdApi,
    options?: RequestInit
): Promise<HogReportDTOApi> => {
    return apiMutator<HogReportDTOApi>(getHogsReportsReadCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reportIdApi),
    })
}

export const getHogsReportsVerdictCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/reports/verdict/`
}

/**
 * Resolve, dismiss or reopen a report.
 */
export const hogsReportsVerdictCreate = async (
    projectId: string,
    id: string,
    reportVerdictApi: ReportVerdictApi,
    options?: RequestInit
): Promise<HogReportDTOApi> => {
    return apiMutator<HogReportDTOApi>(getHogsReportsVerdictCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reportVerdictApi),
    })
}

export const getHogsRulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/rules/`
}

/**
 * List the owner's standing rules for a hog's actions.
 */
export const hogsRulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<HogRuleDTOApi[]> => {
    return apiMutator<HogRuleDTOApi[]>(getHogsRulesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogsRulesSetCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/rules/set/`
}

/**
 * Set the standing rule for one kind of action by this hog.
 */
export const hogsRulesSetCreate = async (
    projectId: string,
    id: string,
    setRuleApi: SetRuleApi,
    options?: RequestInit
): Promise<HogRuleDTOApi> => {
    return apiMutator<HogRuleDTOApi>(getHogsRulesSetCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(setRuleApi),
    })
}

export const getHogsSayCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/say/`
}

/**
 * Send a chat message to the owner, as the hog.
 */
export const hogsSayCreate = async (
    projectId: string,
    id: string,
    messageContentApi: MessageContentApi,
    options?: RequestInit
): Promise<HogMessageDTOApi> => {
    return apiMutator<HogMessageDTOApi>(getHogsSayCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageContentApi),
    })
}

export const getHogsSchedulesRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/schedules/`
}

/**
 * List the schedules that will wake this hog.
 */
export const hogsSchedulesRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<HogScheduleDTOApi[]> => {
    return apiMutator<HogScheduleDTOApi[]>(getHogsSchedulesRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogsSchedulesCreateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/schedules/create/`
}

/**
 * Schedule a future wake for this hog, once or on a repeat.
 */
export const hogsSchedulesCreateCreate = async (
    projectId: string,
    id: string,
    createHogScheduleApi: CreateHogScheduleApi,
    options?: RequestInit
): Promise<HogScheduleDTOApi> => {
    return apiMutator<HogScheduleDTOApi>(getHogsSchedulesCreateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createHogScheduleApi),
    })
}

export const getHogsSchedulesDeleteCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/schedules/delete/`
}

/**
 * Delete one of this hog's schedules.
 */
export const hogsSchedulesDeleteCreate = async (
    projectId: string,
    id: string,
    hogScheduleIdApi: HogScheduleIdApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogsSchedulesDeleteCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogScheduleIdApi),
    })
}

export const getHogsSendCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/send/`
}

/**
 * Send a message to a hog as its owner. The hog wakes and decides whether to reply.
 */
export const hogsSendCreate = async (
    projectId: string,
    id: string,
    messageContentApi: MessageContentApi,
    options?: RequestInit
): Promise<HogMessageDTOApi> => {
    return apiMutator<HogMessageDTOApi>(getHogsSendCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(messageContentApi),
    })
}

export const getHogsTellCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/tell/`
}

/**
 * Send a note from this hog to another hog, which wakes to read it.
 */
export const hogsTellCreate = async (
    projectId: string,
    id: string,
    tellHogApi: TellHogApi,
    options?: RequestInit
): Promise<HogMessageDTOApi> => {
    return apiMutator<HogMessageDTOApi>(getHogsTellCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(tellHogApi),
    })
}

export const getHogsTriggersRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/triggers/`
}

/**
 * List the triggers that wake this hog on an outside event.
 */
export const hogsTriggersRetrieve = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<HogTriggerDTOApi[]> => {
    return apiMutator<HogTriggerDTOApi[]>(getHogsTriggersRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getHogsTriggersFireCreateUrl = (projectId: string, id: string, triggerId: string) => {
    return `/api/projects/${projectId}/hogs/${id}/triggers/${triggerId}/fire/`
}

/**
 * Deliver an event to a trigger. The whole JSON body is the event.
 *
 * Send an `Idempotency-Key` header, or an `id` in the body, so a repeated delivery is dropped.
 */
export const hogsTriggersFireCreate = async (
    projectId: string,
    id: string,
    triggerId: string,
    hogsTriggersFireCreateBody?:
        | HogsTriggersFireCreateBodyOne
        | HogsTriggersFireCreateBodyTwo
        | HogsTriggersFireCreateBodyThree,
    options?: RequestInit
): Promise<HogEventDTOApi> => {
    return apiMutator<HogEventDTOApi>(getHogsTriggersFireCreateUrl(projectId, id, triggerId), {
        ...options,
        method: 'POST',
        body: JSON.stringify(hogsTriggersFireCreateBody),
    })
}

export const getHogsTriggersCreateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/triggers/create/`
}

/**
 * Create a trigger: an address that wakes this hog when something posts an event to it.
 */
export const hogsTriggersCreateCreate = async (
    projectId: string,
    id: string,
    createHogTriggerApi: CreateHogTriggerApi,
    options?: RequestInit
): Promise<HogTriggerDTOApi> => {
    return apiMutator<HogTriggerDTOApi>(getHogsTriggersCreateCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createHogTriggerApi),
    })
}

export const getHogsTriggersDeleteCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/hogs/${id}/triggers/delete/`
}

/**
 * Delete one of this hog's triggers.
 */
export const hogsTriggersDeleteCreate = async (
    projectId: string,
    id: string,
    hogTriggerIdApi: HogTriggerIdApi,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getHogsTriggersDeleteCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(hogTriggerIdApi),
    })
}
