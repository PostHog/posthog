import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { create } from 'zustand'

import { fetchOrganization } from '@/api/users'

import { addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useDemoMode } from '@/demo/demoMode'
import { orgAiSettingsUrl, type ProjectOrganization, projectOrganization } from '@/features/chat/aiAccess'
import { aiConsentKey, useAiConsentStore, waitForAiConsent } from '@/features/chat/aiConsentStore'

export type AiAction = 'chat' | 'handoff' | 'replay'

export type AiAccess =
    | { kind: 'org_unknown' }
    | { kind: 'org_blocked'; organizationName: string | null; settingsUrl: string | null; canApprove: boolean }
    | { kind: 'needs_consent' }
    | { kind: 'ready' }

/**
 * The project an AI action runs in. A report a web link opened runs in the link's project, so the approval that
 * counts is the one of that project's organization, not the session's.
 */
export type AiProject = number | null | undefined

function aiProjectId(project: AiProject): number | null {
    return project ?? useAuthStore.getState().projectId
}

export function currentAiIdentity(): string | null {
    const { status, host, user, projectId } = useAuthStore.getState()
    return status === 'signed_in' && host && user && projectId !== null
        ? JSON.stringify([host, user.uuid, projectId, sessionGeneration()])
        : null
}

export function currentAiAccess(verifiedOrganization?: ProjectOrganization, project?: AiProject): AiAccess {
    const auth = useAuthStore.getState()
    const { host, user } = auth
    const projectId = aiProjectId(project)
    if (!currentAiIdentity() || !host || !user || projectId === null) {
        return { kind: 'org_unknown' }
    }
    const organization = verifiedOrganization ?? projectOrganization(auth.organizations, auth.projects, projectId)
    if (organization.status === 'unknown') {
        return { kind: 'org_unknown' }
    }
    if (organization.status === 'not_approved') {
        return {
            kind: 'org_blocked',
            organizationName: organization.name,
            canApprove: organization.canApprove,
            settingsUrl: organization.canApprove ? orgAiSettingsUrl({ host, projectId }) : null,
        }
    }
    return useAiConsentStore.getState().accepted[aiConsentKey(host, user.uuid)]
        ? { kind: 'ready' }
        : { kind: 'needs_consent' }
}

/** An organization the cached account cannot name fails here, so an unverifiable project never reaches an AI call. */
export async function refreshAiOrganization(
    identity: string,
    signal?: AbortSignal,
    targetProject?: AiProject
): Promise<ProjectOrganization> {
    const projectId = aiProjectId(targetProject)
    // A link can open a report in a project the account was cached before, so a stale list is not the last word.
    if (projectId !== null && !useAuthStore.getState().projects.some((candidate) => candidate.id === projectId)) {
        await useAuthStore.getState().reloadAccount()
    }
    const project = useAuthStore.getState().projects.find((candidate) => candidate.id === projectId)
    if (!project || currentAiIdentity() !== identity) {
        throw new Error('No current project')
    }
    const fresh = await fetchOrganization(project.organizationId, { signal })
    if (currentAiIdentity() !== identity || signal?.aborted) {
        throw new Error('Account or project changed')
    }
    if (fresh.id !== project.organizationId || !fresh.teams.some((team) => team.id === project.id)) {
        throw new Error('Project access changed')
    }
    useAuthStore.setState((state) => ({
        organizations: state.organizations.map((organization) =>
            organization.id === fresh.id
                ? {
                      ...organization,
                      aiDataProcessingApproved:
                          fresh.is_ai_data_processing_approved === undefined
                              ? undefined
                              : fresh.is_ai_data_processing_approved === true,
                      membershipLevel: fresh.membership_level,
                  }
                : organization
        ),
    }))
    return {
        name: fresh.name,
        status:
            fresh.is_ai_data_processing_approved === undefined
                ? 'unknown'
                : fresh.is_ai_data_processing_approved === true
                  ? 'approved'
                  : 'not_approved',
        canApprove: fresh.membership_level === 8 || fresh.membership_level === 15,
    }
}

interface ApprovalRequest {
    identity: string
    action: AiAction
    project: AiProject
    access: AiAccess | null
    checking: boolean
}

interface AiApprovalState {
    request: ApprovalRequest | null
}

export const useAiApprovalStore = create<AiApprovalState>()(() => ({ request: null }))

let pending: { request: ApprovalRequest; signal?: AbortSignal; finish: (approved: boolean) => void } | null = null

export function cancelAiApproval(): void {
    pending?.finish(false)
}

export async function checkAiApproval(accept = false): Promise<void> {
    const operation = pending
    if (!operation || operation.request.checking) {
        return
    }
    operation.request = { ...operation.request, checking: true }
    useAiApprovalStore.setState({ request: operation.request })
    const { identity, project } = operation.request
    try {
        const organization = await refreshAiOrganization(identity, operation.signal, project)
        await waitForAiConsent()
        if (pending !== operation) {
            return
        }
        if (currentAiIdentity() !== identity || useDemoMode.getState().enabled) {
            operation.finish(false)
            return
        }
        let access = currentAiAccess(organization, project)
        if (accept && access.kind === 'needs_consent') {
            const { host, user } = useAuthStore.getState()
            if (host && user) {
                useAiConsentStore.getState().accept(aiConsentKey(host, user.uuid))
            }
            access = currentAiAccess(organization, project)
        }
        if (access.kind === 'ready') {
            operation.finish(true)
            return
        }
        operation.request = { ...operation.request, access, checking: false }
    } catch {
        if (pending !== operation) {
            return
        }
        operation.request = { ...operation.request, access: { kind: 'org_unknown' }, checking: false }
    }
    if (pending === operation) {
        useAiApprovalStore.setState({ request: operation.request })
    }
}

/** Refresh approval before every AI action, including messages that waited in a queue. */
export async function requestAiApproval(action: AiAction, signal?: AbortSignal, project?: AiProject): Promise<boolean> {
    if (signal?.aborted) {
        return false
    }
    if (useDemoMode.getState().enabled) {
        return true
    }
    const identity = currentAiIdentity()
    if (!identity || pending) {
        return false
    }
    return new Promise<boolean>((resolve) => {
        const request: ApprovalRequest = { identity, action, project, access: null, checking: false }
        const abort = (): void => operation.finish(false)
        const unsubscribe = useAuthStore.subscribe(() => {
            if (currentAiIdentity() !== identity) {
                operation.finish(false)
            }
        })
        const operation = {
            request,
            signal,
            finish: (approved: boolean): void => {
                if (pending !== operation) {
                    return
                }
                pending = null
                unsubscribe()
                signal?.removeEventListener('abort', abort)
                useAiApprovalStore.setState({ request: null })
                resolve(approved && currentAiIdentity() === identity)
            },
        }
        pending = operation
        signal?.addEventListener('abort', abort, { once: true })
        void checkAiApproval()
    })
}

addSessionEndTask(cancelAiApproval)

export function useAiApproval(
    action: AiAction,
    context: string,
    project?: AiProject
): { request: () => Promise<boolean>; pending: boolean; signal: AbortSignal } {
    const sessionIdentity = useAuthStore((state) =>
        JSON.stringify([state.host, state.projectId, state.user?.uuid, state.status])
    )
    const identity = JSON.stringify([sessionIdentity, project ?? null])
    const lifetime = useMemo(() => ({ identity, context, controller: new AbortController() }), [identity, context])
    const inFlight = useRef(false)
    const [checking, setChecking] = useState(false)
    useEffect(() => () => lifetime.controller.abort(), [lifetime])
    const request = useCallback(async (): Promise<boolean> => {
        if (inFlight.current || lifetime.controller.signal.aborted) {
            return false
        }
        inFlight.current = true
        setChecking(true)
        try {
            return await requestAiApproval(action, lifetime.controller.signal, project)
        } finally {
            inFlight.current = false
            setChecking(false)
        }
    }, [action, lifetime, project])
    return { request, pending: checking, signal: lifetime.controller.signal }
}
