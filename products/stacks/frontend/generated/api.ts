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
    AdoptRequestApi,
    AdoptResponseApi,
    AdoptablePageApi,
    BindingApi,
    BindingLookupApi,
    ContextPagesRequestApi,
    CreateDiffRequestApi,
    GenerateModuleRequestApi,
    GeneratedModuleApi,
    ManagedKindListApi,
    PaginatedBindingListApi,
    PushRequestApi,
    ReconcileRequestApi,
    ReconciledApi,
    SecretApi,
    SecretListApi,
    SecretWriteApi,
    StackChangeRequestApi,
    StackDiffApi,
    StackSettingsApi,
    StacksAdoptableListParams,
    StacksBindingLookupParams,
    StartedChangeRequestApi,
} from './api.schemas'

export const getStacksAdoptUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/stacks/${name}/adopt/`
}

/**
 * Record pending bindings, so the next push binds these entities and creates nothing. Each entity must exist and be one you can edit. Needs the write scopes of each kind.
 * @summary Adopt existing entities
 */
export const stacksAdopt = async (
    projectId: string,
    name: string,
    adoptRequestApi: AdoptRequestApi,
    options?: RequestInit
): Promise<AdoptResponseApi> => {
    return apiMutator<AdoptResponseApi>(getStacksAdoptUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(adoptRequestApi),
    })
}

export const getStacksBindingsListUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/stacks/${name}/bindings/`
}

/**
 * Each entity the stack manages or has adopted, one page per call.
 * @summary List a stack's bindings
 */
export const stacksBindingsList = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<PaginatedBindingListApi> => {
    return apiMutator<PaginatedBindingListApi>(getStacksBindingsListUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

export const getStacksChangeRequestCreateUrl = (projectId: string, name: string, bindingId: string) => {
    return `/api/projects/${projectId}/stacks/${name}/bindings/${bindingId}/change_requests/`
}

/**
 * Start a cloud task that edits this entity's definition in the stack's repository and opens a pull request. Nothing in PostHog changes until that pull request is merged and pushed.
 * @summary Ask for a change in code
 */
export const stacksChangeRequestCreate = async (
    projectId: string,
    name: string,
    bindingId: string,
    stackChangeRequestApi: StackChangeRequestApi,
    options?: RequestInit
): Promise<StartedChangeRequestApi> => {
    return apiMutator<StartedChangeRequestApi>(getStacksChangeRequestCreateUrl(projectId, name, bindingId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(stackChangeRequestApi),
    })
}

export const getStacksBindingDetachUrl = (projectId: string, name: string, bindingId: string) => {
    return `/api/projects/${projectId}/stacks/${name}/bindings/${bindingId}/detach/`
}

/**
 * Release the entity to the UI. The stack no longer manages it, and nothing is deleted. Needs the write scopes of the entity's kind.
 * @summary Detach an entity
 */
export const stacksBindingDetach = async (
    projectId: string,
    name: string,
    bindingId: string,
    options?: RequestInit
): Promise<BindingApi> => {
    return apiMutator<BindingApi>(getStacksBindingDetachUrl(projectId, name, bindingId), {
        ...options,
        method: 'POST',
    })
}

export const getStacksContextPagesSetUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/stacks/${name}/context_pages/`
}

/**
 * Turn context pages on or off for this stack. Context pages belong to the organization's one wiki, so only an organization admin can turn this on. Off by default.
 * @summary Let a stack manage context pages
 */
export const stacksContextPagesSet = async (
    projectId: string,
    name: string,
    contextPagesRequestApi: ContextPagesRequestApi,
    options?: RequestInit
): Promise<StackSettingsApi> => {
    return apiMutator<StackSettingsApi>(getStacksContextPagesSetUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(contextPagesRequestApi),
    })
}

export const getStacksDiffCreateUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/stacks/${name}/diffs/`
}

/**
 * Save a diff of the description against the project and start computing it. Returns at once with status `running`. Creates the stack on its first diff. Needs the read scopes of every kind in the description and every kind the stack already manages.
 * @summary Start a diff
 */
export const stacksDiffCreate = async (
    projectId: string,
    name: string,
    createDiffRequestApi: CreateDiffRequestApi,
    options?: RequestInit
): Promise<StackDiffApi> => {
    return apiMutator<StackDiffApi>(getStacksDiffCreateUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(createDiffRequestApi),
    })
}

export const getStacksDiffRetrieveUrl = (projectId: string, name: string, diffId: string) => {
    return `/api/projects/${projectId}/stacks/${name}/diffs/${diffId}/`
}

/**
 * The diff and its status. A push's progress shows here too. Needs the read scopes the diff ran with. Field values are shown to the person who made the diff and to project admins.
 * @summary Read a diff
 */
export const stacksDiffRetrieve = async (
    projectId: string,
    name: string,
    diffId: string,
    options?: RequestInit
): Promise<StackDiffApi> => {
    return apiMutator<StackDiffApi>(getStacksDiffRetrieveUrl(projectId, name, diffId), {
        ...options,
        method: 'GET',
    })
}

export const getStacksDiffPushUrl = (projectId: string, name: string, diffId: string) => {
    return `/api/projects/${projectId}/stacks/${name}/diffs/${diffId}/push/`
}

/**
 * Push exactly this saved diff. Refused with `stack_moved` when the stack changed since the diff was made. Returns at once with status `running`. Needs the read and write scopes of every kind the push touches.
 * @summary Push a diff
 */
export const stacksDiffPush = async (
    projectId: string,
    name: string,
    diffId: string,
    pushRequestApi?: PushRequestApi,
    options?: RequestInit
): Promise<StackDiffApi> => {
    return apiMutator<StackDiffApi>(getStacksDiffPushUrl(projectId, name, diffId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(pushRequestApi),
    })
}

export const getStacksReconcileUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/stacks/${name}/reconcile/`
}

/**
 * After a push stopped without a known outcome, accept a ready diff computed since then, with its warnings about entities the push may already have created. Adopt those first if they should not be created again. The stack can push again afterwards.
 * @summary Reconcile after an uncertain push
 */
export const stacksReconcile = async (
    projectId: string,
    name: string,
    reconcileRequestApi: ReconcileRequestApi,
    options?: RequestInit
): Promise<ReconciledApi> => {
    return apiMutator<ReconciledApi>(getStacksReconcileUrl(projectId, name), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(reconcileRequestApi),
    })
}

export const getStacksSecretsListUrl = (projectId: string, name: string) => {
    return `/api/projects/${projectId}/stacks/${name}/secrets/`
}

/**
 * The names of the stack's secrets and when each was last set. Never their values.
 * @summary List secrets
 */
export const stacksSecretsList = async (
    projectId: string,
    name: string,
    options?: RequestInit
): Promise<SecretListApi> => {
    return apiMutator<SecretListApi>(getStacksSecretsListUrl(projectId, name), {
        ...options,
        method: 'GET',
    })
}

export const getStacksSecretSetUrl = (projectId: string, name: string, secretName: string) => {
    return `/api/projects/${projectId}/stacks/${name}/secrets/${secretName}/`
}

/**
 * Set or replace the value a definition names with `secret('NAME')`. The value is encrypted and never returned. Creates the stack if it does not exist yet.
 * @summary Set a secret
 */
export const stacksSecretSet = async (
    projectId: string,
    name: string,
    secretName: string,
    secretWriteApi: SecretWriteApi,
    options?: RequestInit
): Promise<SecretApi> => {
    return apiMutator<SecretApi>(getStacksSecretSetUrl(projectId, name, secretName), {
        ...options,
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(secretWriteApi),
    })
}

export const getStacksSecretRemoveUrl = (projectId: string, name: string, secretName: string) => {
    return `/api/projects/${projectId}/stacks/${name}/secrets/${secretName}/`
}

/**
 * Remove a secret from the stack. A diff that still names it fails with `secret_missing`.
 * @summary Remove a secret
 */
export const stacksSecretRemove = async (
    projectId: string,
    name: string,
    secretName: string,
    options?: RequestInit
): Promise<void> => {
    return apiMutator<void>(getStacksSecretRemoveUrl(projectId, name, secretName), {
        ...options,
        method: 'DELETE',
    })
}

export const getStacksAdoptableListUrl = (projectId: string, params: StacksAdoptableListParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/stacks/adoptable/?${stringifiedParams}`
        : `/api/projects/${projectId}/stacks/adoptable/`
}

/**
 * Entities of one kind that no stack manages and that you can read, with bodies in description shape. Follow `next` for the next page. Needs the read scopes of the kind.
 * @summary List adoptable entities
 */
export const stacksAdoptableList = async (
    projectId: string,
    params: StacksAdoptableListParams,
    options?: RequestInit
): Promise<AdoptablePageApi> => {
    return apiMutator<AdoptablePageApi>(getStacksAdoptableListUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getStacksBindingLookupUrl = (projectId: string, params: StacksBindingLookupParams) => {
    const normalizedParams = new URLSearchParams()

    Object.entries(params || {}).forEach(([key, value]) => {
        if (value !== undefined) {
            normalizedParams.append(key, value === null ? 'null' : String(value))
        }
    })

    const stringifiedParams = normalizedParams.toString()

    return stringifiedParams.length > 0
        ? `/api/projects/${projectId}/stacks/bindings/?${stringifiedParams}`
        : `/api/projects/${projectId}/stacks/bindings/`
}

/**
 * The binding that manages this entity, or null when no stack does.
 * @summary Find what manages an entity
 */
export const stacksBindingLookup = async (
    projectId: string,
    params: StacksBindingLookupParams,
    options?: RequestInit
): Promise<BindingLookupApi> => {
    return apiMutator<BindingLookupApi>(getStacksBindingLookupUrl(projectId, params), {
        ...options,
        method: 'GET',
    })
}

export const getStacksManagedKindsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/stacks/managed_kinds/`
}

/**
 * Each kind of entity some stack in this project manages, with the stack and its repository. Before creating an entity of a listed kind, add its definition in that repository instead.
 * @summary List the kinds managed in code
 */
export const stacksManagedKindsList = async (projectId: string, options?: RequestInit): Promise<ManagedKindListApi> => {
    return apiMutator<ManagedKindListApi>(getStacksManagedKindsListUrl(projectId), {
        ...options,
        method: 'GET',
    })
}

export const getStacksModuleGenerateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/stacks/modules/`
}

/**
 * The typed module for one language that the events of a stack description give. Nothing is stored and no stack is created.
 * @summary Generate a typed module
 */
export const stacksModuleGenerate = async (
    projectId: string,
    generateModuleRequestApi: GenerateModuleRequestApi,
    options?: RequestInit
): Promise<GeneratedModuleApi> => {
    return apiMutator<GeneratedModuleApi>(getStacksModuleGenerateUrl(projectId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(generateModuleRequestApi),
    })
}
