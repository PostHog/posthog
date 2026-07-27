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
    BetDTOApi,
    BetEventDTOApi,
    BetNodeDTOApi,
    CreateBetApi,
    CreateBetEventApi,
    RecordVerdictApi,
} from './api.schemas'

export const getBetsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/bets/`
}

/**
 * List the project's bets, newest first.
 */
export const betsList = async (projectId: string, options?: RequestInit): Promise<BetDTOApi[]> => {
    return apiMutator<BetDTOApi[]>(getBetsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getBetsCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/bets/`
}

/**
 * Create a bet in the drafted state.
 */
export const betsCreate = async (
    projectId: string,
    createBetApi: CreateBetApi,
    options?: RequestInit
): Promise<BetDTOApi> => {
    return apiMutator<BetDTOApi>(getBetsCreateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createBetApi),
    })
}

export const getBetsRetrieveUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/`
}

/**
 * Retrieve a single bet.
 */
export const betsRetrieve = async (projectId: string, id: string, options?: RequestInit): Promise<BetDTOApi> => {
    return apiMutator<BetDTOApi>(getBetsRetrieveUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBetsEventsListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/events/`
}

/**
 * List the bet's append-only event log, oldest first.
 */
export const betsEventsList = async (
    projectId: string,
    id: string,
    options?: RequestInit
): Promise<BetEventDTOApi[]> => {
    return apiMutator<BetEventDTOApi[]>(getBetsEventsListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBetsEventsCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/events/`
}

/**
 * Append a typed orchestrator event (run.started, node.spawned, gate.result, exposure.started, ...) and drive any state transition it implies. Events are immutable — there is no update or delete.
 */
export const betsEventsCreate = async (
    projectId: string,
    id: string,
    createBetEventApi: CreateBetEventApi,
    options?: RequestInit
): Promise<BetEventDTOApi> => {
    return apiMutator<BetEventDTOApi>(getBetsEventsCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createBetEventApi),
    })
}

export const getBetsFundCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/fund/`
}

/**
 * Fund a drafted bet: creates its feature flag ('bet-<slug>') and a draft experiment, then moves it to funded.
 */
export const betsFundCreate = async (projectId: string, id: string, options?: RequestInit): Promise<BetDTOApi> => {
    return apiMutator<BetDTOApi>(getBetsFundCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
    })
}

export const getBetsNodesListUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/nodes/`
}

/**
 * List the bet's node tree, as projected from node.spawned/node.finished/node.failed events.
 */
export const betsNodesList = async (projectId: string, id: string, options?: RequestInit): Promise<BetNodeDTOApi[]> => {
    return apiMutator<BetNodeDTOApi[]>(getBetsNodesListUrl(projectId, id), {
        ...options,
        method: 'GET',
    })
}

export const getBetsVerdictCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/bets/${id}/verdict/`
}

/**
 * Record the market verdict on an exposed bet.
 */
export const betsVerdictCreate = async (
    projectId: string,
    id: string,
    recordVerdictApi: RecordVerdictApi,
    options?: RequestInit
): Promise<BetDTOApi> => {
    return apiMutator<BetDTOApi>(getBetsVerdictCreateUrl(projectId, id), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(recordVerdictApi),
    })
}
