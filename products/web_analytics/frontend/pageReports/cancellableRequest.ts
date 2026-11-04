import { BreakPointFunction, isBreakpoint } from 'kea'

import { uuid } from 'lib/utils/dom'
import { isAbortedRequest, isTimedOutRequest } from 'lib/utils/requests'

import { cancelQueryOnServer } from '~/queries/nodes/DataNode/dataNodeLogic'

interface RequestDisposables {
    add: (setup: () => () => void, key: string, options: { pauseOnPageHidden: boolean }) => void
}

export interface CancellableRequest {
    signal: AbortSignal
    queryId: string
    track: <T>(request: Promise<T>) => Promise<T>
}

export const startCancellableRequest = (
    disposables: RequestDisposables,
    key: string,
    getTeamId: () => number | null
): CancellableRequest => {
    const abortController = new AbortController()
    const queryId = uuid()
    let finished = false
    disposables.add(
        () => () => {
            abortController.abort()
            if (!finished) {
                void cancelQueryOnServer(getTeamId(), queryId)
            }
        },
        key,
        { pauseOnPageHidden: false }
    )
    return {
        signal: abortController.signal,
        queryId,
        track: (request) =>
            request.then(
                (result) => {
                    finished = true
                    return result
                },
                (error) => {
                    if (isTimedOutRequest(error)) {
                        void cancelQueryOnServer(getTeamId(), queryId)
                    }
                    finished = true
                    throw error
                }
            ),
    }
}

export const runCancellableRequest = async <T>(
    disposables: RequestDisposables,
    key: string,
    getTeamId: () => number | null,
    breakpoint: BreakPointFunction,
    load: (request: CancellableRequest) => Promise<T>
): Promise<T> => {
    const request = startCancellableRequest(disposables, key, getTeamId)
    try {
        const result = await request.track(load(request))
        breakpoint()
        return result
    } catch (error) {
        breakpoint()
        throw error
    }
}

export const isCancelledRequest = (error: unknown): boolean =>
    (error instanceof Error && isBreakpoint(error)) || isAbortedRequest(error)
