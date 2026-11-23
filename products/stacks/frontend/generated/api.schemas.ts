/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface AdoptResourceApi {
    /**
     * The definition kind of the entity. One of `flag`, `event`, `property_group`, `model`, `endpoint`, `metric`, `context_page`, `insight`, `dashboard`, `alert`, `destination`, `cohort`, `action`, `source`, `check`, `experiment` or `survey`.
     * @maxLength 64
     */
    kind: string
    /**
     * The key the definition will use in the stack.
     * @maxLength 512
     */
    key: string
    /**
     * The id of the existing entity in PostHog.
     * @maxLength 512
     */
    entity_id: string
}

export interface AdoptRequestApi {
    /** The entities to bind. The next push binds them and creates nothing. */
    resources: AdoptResourceApi[]
}

export interface DefinitionSourceRefApi {
    /** Path of the definition's file, relative to the repo root. */
    file: string
    /** Name of the export in that file. */
    export?: string
}

/**
 * * `pending` - Pending
 * * `bound` - Bound
 * * `detached` - Detached
 */
export type BindingStatusEnumApi = (typeof BindingStatusEnumApi)[keyof typeof BindingStatusEnumApi]

export const BindingStatusEnumApi = {
    Pending: 'pending',
    Bound: 'bound',
    Detached: 'detached',
} as const

export interface BindingApi {
    /** The binding id. Detach takes this id. */
    id: string
    /** The stack that manages the entity. */
    stack_name: string
    /** The repository the stack was last pushed from. Empty before a push. */
    repository: string
    /** The definition kind. */
    kind: string
    /** The definition key. */
    key: string
    /** The id of the entity in PostHog. */
    entity_id: string
    /**
     * Where the entity opens in PostHog. Null for some kinds.
     * @nullable
     */
    entity_url: string | null
    /** Where the definition lives in the repository. */
    source: DefinitionSourceRefApi | null
    /** `bound` once a push made or adopted the entity, `pending` when adopt recorded it and no push ran yet, `detached` once released to the UI.
     *
     * * `pending` - Pending
     * * `bound` - Bound
     * * `detached` - Detached */
    status: BindingStatusEnumApi
    /** The fields code owns, as sorted dotted paths into the definition body, such as `name` or `filters.payloads`. A write to one of them is refused with `managed_in_code`. Empty when code owns none. */
    owned_fields: string[]
}

export interface AdoptResponseApi {
    /** The pending bindings adopt recorded. */
    bindings: BindingApi[]
}

/**
 * More about the error. `required_scopes` for a missing scope. For `managed_in_code`: `kind`, `binding_id`, `stack`, `repository`, `source` and `fields`.
 */
export type StackErrorResponseApiExtra = { [key: string]: unknown }

/**
 * * `stack_not_found` - Stack Not Found
 * * `diff_not_found` - Diff Not Found
 * * `binding_not_found` - Binding Not Found
 * * `secret_not_found` - Secret Not Found
 * * `entity_not_found` - Entity Not Found
 * * `stack_moved` - Stack Moved
 * * `stack_locked` - Stack Locked
 * * `diff_not_ready` - Diff Not Ready
 * * `diff_pushed` - Diff Pushed
 * * `diff_expired` - Diff Expired
 * * `push_uncertain` - Push Uncertain
 * * `claimed_by_other_stack` - Claimed By Other Stack
 * * `entity_already_bound` - Entity Already Bound
 * * `key_already_bound` - Key Already Bound
 * * `too_many_removals` - Too Many Removals
 * * `invalid_stack_name` - Invalid Stack Name
 * * `invalid_secret_name` - Invalid Secret Name
 * * `secret_too_large` - Secret Too Large
 * * `invalid_key` - Invalid Key
 * * `duplicate_definition` - Duplicate Definition
 * * `too_many_definitions` - Too Many Definitions
 * * `definition_too_large` - Definition Too Large
 * * `definition_too_deep` - Definition Too Deep
 * * `secret_literal` - Secret Literal
 * * `invalid_definition` - Invalid Definition
 * * `kind_unsupported` - Kind Unsupported
 * * `impersonated_push` - Impersonated Push
 * * `user_required` - User Required
 * * `caller_unavailable` - Caller Unavailable
 * * `permission_denied` - Permission Denied
 * * `stacks_unavailable` - Stacks Unavailable
 * * `runner_unavailable` - Runner Unavailable
 * * `invalid_input` - Invalid Input
 * * `context_pages_not_enabled` - Context Pages Not Enabled
 * * `organization_admin_required` - Organization Admin Required
 * * `kind_not_listable` - Kind Not Listable
 * * `managed_in_code` - Managed In Code
 * * `repository_not_connected` - Repository Not Connected
 * * `tasks_unavailable` - Tasks Unavailable
 * * `nothing_to_reconcile` - Nothing To Reconcile
 * * `credential_not_supported` - Credential Not Supported
 * * `secret_missing` - Secret Missing
 */
export type StackErrorCodeEnumApi = (typeof StackErrorCodeEnumApi)[keyof typeof StackErrorCodeEnumApi]

export const StackErrorCodeEnumApi = {
    StackNotFound: 'stack_not_found',
    DiffNotFound: 'diff_not_found',
    BindingNotFound: 'binding_not_found',
    SecretNotFound: 'secret_not_found',
    EntityNotFound: 'entity_not_found',
    StackMoved: 'stack_moved',
    StackLocked: 'stack_locked',
    DiffNotReady: 'diff_not_ready',
    DiffPushed: 'diff_pushed',
    DiffExpired: 'diff_expired',
    PushUncertain: 'push_uncertain',
    ClaimedByOtherStack: 'claimed_by_other_stack',
    EntityAlreadyBound: 'entity_already_bound',
    KeyAlreadyBound: 'key_already_bound',
    TooManyRemovals: 'too_many_removals',
    InvalidStackName: 'invalid_stack_name',
    InvalidSecretName: 'invalid_secret_name',
    SecretTooLarge: 'secret_too_large',
    InvalidKey: 'invalid_key',
    DuplicateDefinition: 'duplicate_definition',
    TooManyDefinitions: 'too_many_definitions',
    DefinitionTooLarge: 'definition_too_large',
    DefinitionTooDeep: 'definition_too_deep',
    SecretLiteral: 'secret_literal',
    InvalidDefinition: 'invalid_definition',
    KindUnsupported: 'kind_unsupported',
    ImpersonatedPush: 'impersonated_push',
    UserRequired: 'user_required',
    CallerUnavailable: 'caller_unavailable',
    PermissionDenied: 'permission_denied',
    StacksUnavailable: 'stacks_unavailable',
    RunnerUnavailable: 'runner_unavailable',
    InvalidInput: 'invalid_input',
    ContextPagesNotEnabled: 'context_pages_not_enabled',
    OrganizationAdminRequired: 'organization_admin_required',
    KindNotListable: 'kind_not_listable',
    ManagedInCode: 'managed_in_code',
    RepositoryNotConnected: 'repository_not_connected',
    TasksUnavailable: 'tasks_unavailable',
    NothingToReconcile: 'nothing_to_reconcile',
    CredentialNotSupported: 'credential_not_supported',
    SecretMissing: 'secret_missing',
} as const

export interface StackErrorResponseApi {
    /** The error class, such as `invalid_request` or `authentication_error`. */
    type: string
    /** A stable code for the error. `stack_moved`: run diff again. `stack_locked`: wait for the running push. `diff_expired`: run diff again. `push_uncertain`: run diff, review its warnings, then reconcile. `permission_denied` with `required_scopes`: the key lacks a scope the run needs. `nothing_to_reconcile`: the stack has no uncertain push. `managed_in_code`: edit the definition in the repository instead.
     *
     * * `stack_not_found` - Stack Not Found
     * * `diff_not_found` - Diff Not Found
     * * `binding_not_found` - Binding Not Found
     * * `secret_not_found` - Secret Not Found
     * * `entity_not_found` - Entity Not Found
     * * `stack_moved` - Stack Moved
     * * `stack_locked` - Stack Locked
     * * `diff_not_ready` - Diff Not Ready
     * * `diff_pushed` - Diff Pushed
     * * `diff_expired` - Diff Expired
     * * `push_uncertain` - Push Uncertain
     * * `claimed_by_other_stack` - Claimed By Other Stack
     * * `entity_already_bound` - Entity Already Bound
     * * `key_already_bound` - Key Already Bound
     * * `too_many_removals` - Too Many Removals
     * * `invalid_stack_name` - Invalid Stack Name
     * * `invalid_secret_name` - Invalid Secret Name
     * * `secret_too_large` - Secret Too Large
     * * `invalid_key` - Invalid Key
     * * `duplicate_definition` - Duplicate Definition
     * * `too_many_definitions` - Too Many Definitions
     * * `definition_too_large` - Definition Too Large
     * * `definition_too_deep` - Definition Too Deep
     * * `secret_literal` - Secret Literal
     * * `invalid_definition` - Invalid Definition
     * * `kind_unsupported` - Kind Unsupported
     * * `impersonated_push` - Impersonated Push
     * * `user_required` - User Required
     * * `caller_unavailable` - Caller Unavailable
     * * `permission_denied` - Permission Denied
     * * `stacks_unavailable` - Stacks Unavailable
     * * `runner_unavailable` - Runner Unavailable
     * * `invalid_input` - Invalid Input
     * * `context_pages_not_enabled` - Context Pages Not Enabled
     * * `organization_admin_required` - Organization Admin Required
     * * `kind_not_listable` - Kind Not Listable
     * * `managed_in_code` - Managed In Code
     * * `repository_not_connected` - Repository Not Connected
     * * `tasks_unavailable` - Tasks Unavailable
     * * `nothing_to_reconcile` - Nothing To Reconcile
     * * `credential_not_supported` - Credential Not Supported
     * * `secret_missing` - Secret Missing */
    code: StackErrorCodeEnumApi
    /** What went wrong and what to do next. */
    detail: string
    /**
     * The request field the error is about, if any.
     * @nullable
     */
    attr: string | null
    /** More about the error. `required_scopes` for a missing scope. For `managed_in_code`: `kind`, `binding_id`, `stack`, `repository`, `source` and `fields`. */
    extra?: StackErrorResponseApiExtra
}

export interface PaginatedBindingListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BindingApi[]
}

export interface RequestedChangeApi {
    /**
     * The field to change, as a dotted path into the definition body.
     * @maxLength 500
     */
    path: string
    /** The value the person wants the field to have. */
    value: unknown
}

export interface StackChangeRequestApi {
    /**
     * What the person wants changed, in their own words. A cloud task reads it as a description of the change, not as instructions.
     * @maxLength 4000
     */
    note: string
    /**
     * Field values the person asked for, if any.
     * @maxItems 50
     */
    changes?: RequestedChangeApi[]
}

export interface StartedChangeRequestApi {
    /** The cloud task that edits the definition and opens a pull request. */
    task_id: string
    /** Where the task's progress shows in PostHog. */
    task_url: string
}

export interface ContextPagesRequestApi {
    /** Whether this stack may manage context pages. They belong to the organization's one wiki, so only an organization admin can turn this on. */
    enabled: boolean
}

export interface StackSettingsApi {
    /** The stack name. */
    name: string
    /** Whether this stack may manage context pages. */
    context_pages_enabled: boolean
}

export interface DefinitionSourceApi {
    /**
     * Path of the definition's file, relative to the repo root.
     * @maxLength 1000
     */
    file: string
    /**
     * Name of the export in that file that holds the definition.
     * @maxLength 200
     */
    export?: string
}

export interface DefinitionIdentityApi {
    /**
     * The definition kind, such as `model` or `flag`.
     * @maxLength 64
     */
    kind: string
    /**
     * The definition's key in the same stack.
     * @maxLength 512
     */
    key: string
}

/**
 * The definition, shaped like the API's create body for the kind. A reference to another definition in the stack is `{"$ref": {"kind", "key", "attr"}}`, and a secret is `{"$secret": "NAME"}`.
 */
export type ResourceDescriptionApiBody = { [key: string]: unknown }

export interface ResourceDescriptionApi {
    /**
     * The definition kind, such as `insight`, `dashboard`, `flag` or `event`.
     * @maxLength 64
     */
    kind: string
    /**
     * The identity the author chose, unique within the kind. For a kind with a natural key, such as a flag key or an event name, it is that natural key.
     * @maxLength 512
     */
    key: string
    /** The definition, shaped like the API's create body for the kind. A reference to another definition in the stack is `{"$ref": {"kind", "key", "attr"}}`, and a secret is `{"$secret": "NAME"}`. */
    body: ResourceDescriptionApiBody
    /** Where the definition lives in the repository, for messages and provenance. */
    source?: DefinitionSourceApi
    /** Definitions in the same stack that must exist before this one is created, because the body names them by a string rather than a reference, such as a model that another model's SQL reads. */
    depends_on?: DefinitionIdentityApi[]
}

export interface StackDescriptionApi {
    /**
     * The description format version. Always 1.
     * @minimum 1
     * @maximum 1
     */
    version: number
    /** Every definition the stack manages, sorted by kind and then key. */
    resources: ResourceDescriptionApi[]
}

export interface DiffSourceApi {
    /**
     * The repository the description was built from, such as `org/repo`.
     * @maxLength 500
     */
    repository: string
    /**
     * The branch the description was built from.
     * @maxLength 500
     */
    branch: string
    /**
     * The commit the description was built from.
     * @maxLength 100
     */
    commit: string
}

export interface CreateDiffRequestApi {
    /** The stack description that `hog check` writes. */
    description: StackDescriptionApi
    /** The repository, branch and commit the description came from. */
    source: DiffSourceApi
}

/**
 * * `running` - Running
 * * `ready` - Ready
 * * `failed` - Failed
 * * `pushed` - Pushed
 * * `stale` - Stale
 */
export type DiffStatusEnumApi = (typeof DiffStatusEnumApi)[keyof typeof DiffStatusEnumApi]

export const DiffStatusEnumApi = {
    Running: 'running',
    Ready: 'ready',
    Failed: 'failed',
    Pushed: 'pushed',
    Stale: 'stale',
} as const

/**
 * * `create` - Create
 * * `update` - Update
 * * `recreate` - Recreate
 * * `remove` - Remove
 * * `adopt` - Adopt
 * * `rename` - Rename
 * * `release` - Release
 */
export type ChangeActionEnumApi = (typeof ChangeActionEnumApi)[keyof typeof ChangeActionEnumApi]

export const ChangeActionEnumApi = {
    Create: 'create',
    Update: 'update',
    Recreate: 'recreate',
    Remove: 'remove',
    Adopt: 'adopt',
    Rename: 'rename',
    Release: 'release',
} as const

export interface StackFieldChangeApi {
    /** The field that changes, as a dotted path into the definition body. */
    path: string
    /** The value now in PostHog. Null when the field is sensitive. */
    before: unknown
    /** The value a push sets. Null when the field is sensitive. */
    after: unknown
    /** True when the value is secret, so neither value is shown. */
    sensitive: boolean
}

export interface StackChangeApi {
    /** What a push does to this definition.
     *
     * * `create` - Create
     * * `update` - Update
     * * `recreate` - Recreate
     * * `remove` - Remove
     * * `adopt` - Adopt
     * * `rename` - Rename
     * * `release` - Release */
    action: ChangeActionEnumApi
    /** The definition kind. */
    kind: string
    /** The definition key. */
    key: string
    /** The entity's display name. */
    name: string
    /** One line on what changes, such as `query changed`. */
    summary: string
    /** Each field that changes. */
    fields: StackFieldChangeApi[]
    /** Where the definition lives in the repository. */
    source: DefinitionSourceRefApi | null
    /**
     * For a recreate, what a person loses, such as history or links. Null otherwise.
     * @nullable
     */
    loses: string | null
    /** For an adopt, the id of the existing entity the push binds. */
    entity_id?: string
}

export interface DriftFieldApi {
    /** The field that changed outside the code. */
    path: string
    /** The value the last push set. */
    pushed: unknown
    /** The value PostHog holds now. */
    found: unknown
    /** True when the value is secret. */
    sensitive?: boolean
}

export interface DriftApi {
    /** The definition kind. */
    kind: string
    /** The definition key. */
    key: string
    /** True when the entity was deleted in PostHog outside of code. A push creates it again. */
    deleted?: boolean
    /** Each field that changed outside the code. */
    fields: DriftFieldApi[]
}

export interface DiffSummaryApi {
    /** Entities a push creates. */
    create: number
    /** Entities a push changes in place. */
    update: number
    /** Entities a push deletes and creates again. */
    recreate: number
    /** Entities a push removes. */
    remove: number
    /** Existing entities a push binds to the stack. */
    adopt: number
    /** Definitions whose key changes with nothing recreated. */
    rename: number
    /** Entities the stack stops managing and leaves in PostHog: removed definitions of adopted entities, detached entities, and kinds code never deletes. */
    release?: number
}

export interface DiffErrorApi {
    /** A stable code for the error, such as `reference_missing` or `stack_moved`. */
    code: string
    /** What went wrong and what to do next. */
    message: string
    /** The kind of the definition the error is about. */
    kind?: string
    /** The key of the definition the error is about. */
    key?: string
    /** The field of the definition the error is about. */
    path?: string
}

/**
 * * `possible_unrecorded_create` - possible_unrecorded_create
 * * `unrecorded_creates_unchecked` - unrecorded_creates_unchecked
 */
export type DiffWarningCodeEnumApi = (typeof DiffWarningCodeEnumApi)[keyof typeof DiffWarningCodeEnumApi]

export const DiffWarningCodeEnumApi = {
    PossibleUnrecordedCreate: 'possible_unrecorded_create',
    UnrecordedCreatesUnchecked: 'unrecorded_creates_unchecked',
} as const

export interface WarningEntityApi {
    /** The id of the entity in PostHog. Adopt takes this id. */
    entity_id: string
    /** The entity's display name. */
    name: string
}

export interface DiffWarningApi {
    /** `possible_unrecorded_create`: an interrupted push may already have created this definition, and `entities` lists the candidates. `unrecorded_creates_unchecked`: PostHog could not read every entity of the kind, so check in PostHog by hand.
     *
     * * `possible_unrecorded_create` - possible_unrecorded_create
     * * `unrecorded_creates_unchecked` - unrecorded_creates_unchecked */
    code: DiffWarningCodeEnumApi
    /** The definition kind. */
    kind: string
    /**
     * The definition key. Null for a whole kind.
     * @nullable
     */
    key: string | null
    /** What to check and what to do next. */
    message: string
    /** Entities with the definition's name that no stack manages. Adopt one, or reconcile. */
    entities: WarningEntityApi[]
}

export interface DiffResultApi {
    /** What a push would create, change, recreate, remove, adopt or rename. */
    changes: StackChangeApi[]
    /** Entities changed outside the code since the last push. */
    drift: DriftApi[]
    /** The number of changes by action. */
    summary: DiffSummaryApi
    /** Why the diff could not be computed. Empty for a ready diff. */
    errors: DiffErrorApi[]
    /** Only after a push that stopped without a known outcome: entities it may have created without recording them. Adopt them, or reconcile to let this diff create them. */
    warnings?: DiffWarningApi[]
}

/**
 * * `running` - Running
 * * `succeeded` - Succeeded
 * * `failed` - Failed
 * * `uncertain` - Uncertain
 */
export type PushStatusEnumApi = (typeof PushStatusEnumApi)[keyof typeof PushStatusEnumApi]

export const PushStatusEnumApi = {
    Running: 'running',
    Succeeded: 'succeeded',
    Failed: 'failed',
    Uncertain: 'uncertain',
} as const

export interface StackDiffApi {
    /** The diff id. Pushing this id changes PostHog by exactly this diff. */
    id: string
    /** The stack the diff belongs to. */
    stack_name: string
    /** `running` while the diff or its push runs, `ready` to push, `failed` when the diff or its last push failed, `pushed` once pushed, `stale` when the stack changed since the diff was made.
     *
     * * `running` - Running
     * * `ready` - Ready
     * * `failed` - Failed
     * * `pushed` - Pushed
     * * `stale` - Stale */
    status: DiffStatusEnumApi
    /** The diff. Null while it is running. */
    diff: DiffResultApi | null
    /** The repository, branch and commit the description came from. */
    source: DiffSourceApi
    /** When the diff was requested. */
    created_at: string
    /** After this time the diff can no longer be pushed. */
    expires_at: string
    /** The last push of this diff. Null when never pushed.
     *
     * * `running` - Running
     * * `succeeded` - Succeeded
     * * `failed` - Failed
     * * `uncertain` - Uncertain */
    push_status: PushStatusEnumApi | null
    /** Why the last push failed. Empty otherwise. */
    push_errors: DiffErrorApi[]
}

export interface PushRequestApi {
    /**
     * The most entities this push may remove or recreate. Defaults to the stack's own cap. Set it to confirm a push that removes more.
     * @minimum 0
     * @nullable
     */
    max_removals?: number | null
}

export interface ReconcileRequestApi {
    /** A ready diff computed since the uncertain push. Reconciling accepts its warnings. */
    diff_id: string
}

export interface ReconciledApi {
    /** The stack, which can push again. */
    stack_name: string
    /** The diff the person reconciled with. Push it next. */
    diff_id: string
    /** How many warnings of that diff were accepted. */
    acknowledged_warnings: number
}

export interface SecretApi {
    /** The name definitions use in `secret('NAME')`. */
    name: string
    /** When the value was last set. */
    updated_at: string
}

export interface SecretListApi {
    /** Every secret the stack holds, by name. Never the values. */
    results: SecretApi[]
}

export interface SecretWriteApi {
    /**
     * The secret's value. Stored encrypted and never returned. Send it from a file or stdin, never from a command line argument.
     * @maxLength 65536
     */
    value: string
}

/**
 * The entity shaped like a description body, for generating its definition.
 */
export type AdoptableEntityApiBody = { [key: string]: unknown }

export interface AdoptableEntityApi {
    /** The definition kind. */
    kind: string
    /** The id of the entity in PostHog. */
    entity_id: string
    /** The entity's display name. */
    name: string
    /** The entity shaped like a description body, for generating its definition. */
    body: AdoptableEntityApiBody
}

export interface AdoptablePageApi {
    /**
     * Always null: the total is not known before the last page is read.
     * @nullable
     */
    count: number | null
    /**
     * The URL of the next page, or null on the last page.
     * @nullable
     */
    next: string | null
    /**
     * Always null: pages are read forward only.
     * @nullable
     */
    previous: string | null
    /** Entities of the kind that no stack manages. */
    results: AdoptableEntityApi[]
}

export interface BindingLookupApi {
    /** The binding that manages the entity. Null when no stack does. */
    binding: BindingApi | null
}

export interface ManagedKindApi {
    /** A definition kind some stack in this project manages, such as `flag`. */
    kind: string
    /** The stack that manages entities of this kind. */
    stack_name: string
    /** The repository the stack was last pushed from. Edit the code there. */
    repository: string
    /** How many entities of this kind the stack manages. */
    definitions: number
    /** True when this kind's entities are definitions named by a natural key, such as an event or a flag. Do not create one of these outside code: add its definition in the repository instead. */
    redirect_creates: boolean
}

export interface ManagedKindListApi {
    /** One row per kind and stack. Before creating an entity of a listed kind, add it in code. */
    results: ManagedKindApi[]
}

/**
 * * `python` - Python
 * * `golang` - Go
 * * `typescript` - TypeScript
 */
export type ModuleLanguageEnumApi = (typeof ModuleLanguageEnumApi)[keyof typeof ModuleLanguageEnumApi]

export const ModuleLanguageEnumApi = {
    Python: 'python',
    Golang: 'golang',
    Typescript: 'typescript',
} as const

export interface GenerateModuleRequestApi {
    /** The stack description that `check` produced. */
    description: StackDescriptionApi
    /** The language of the module to generate.
     *
     * * `python` - Python
     * * `golang` - Go
     * * `typescript` - TypeScript */
    language: ModuleLanguageEnumApi
}

export interface GeneratedModuleApi {
    /** The module's source code, typed for the events the description declares. */
    content: string
    /** The module's language.
     *
     * * `python` - Python
     * * `golang` - Go
     * * `typescript` - TypeScript */
    language: ModuleLanguageEnumApi
    /** How many events the module covers. */
    event_count: number
    /** A hash of the events and the generator version. A module whose hash differs is stale. */
    schema_hash: string
    /** The version of the generator that wrote the module. */
    generator_version: string
}

export type StacksAdoptableListParams = {
    /**
     * The `cursor` from the previous page's `next` URL.
     * @minLength 1
     * @maxLength 2000
     */
    cursor?: string
    /**
     * The definition kind to list. One of `flag`, `event`, `property_group`, `model`, `endpoint`, `metric`, `context_page`, `insight`, `dashboard`, `alert`, `destination`, `cohort`, `action`, `source`, `check`, `experiment` or `survey`.
     * @minLength 1
     * @maxLength 64
     */
    kind: string
    /**
     * How many entities to read, at most 100.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
}

export type StacksBindingLookupParams = {
    /**
     * The id of the entity in PostHog. For a kind whose key is a name, such as an event name or a context page path, that name finds it too.
     * @minLength 1
     * @maxLength 512
     */
    entity_id: string
    /**
     * The definition kind of the entity. One of `flag`, `event`, `property_group`, `model`, `endpoint`, `metric`, `context_page`, `insight`, `dashboard`, `alert`, `destination`, `cohort`, `action`, `source`, `check`, `experiment` or `survey`.
     * @minLength 1
     * @maxLength 64
     */
    kind: string
}
