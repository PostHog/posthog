export const imageNames = ['base', 'notebook', 'streamlit', 'pi', 'autoresearch', 'vm'] as const
export type ImageName = (typeof imageNames)[number]
export type Evidence = 'current' | 'waiting' | 'building' | 'failed' | 'unknown' | 'unmanaged'
export type Source<T> = {
    status: 'ok' | 'error' | 'refreshing'
    observed_at: string | null
    data: T | null
    error?: string | null
}
export type Platform = {
    arch: string
    version: string | null
    revision: string | null
    base_revision: string | null
    inputs_digest: string | null
    digest: string
}
export type RegistryImage = { name: string; reference: string; platforms: Platform[] }
export type CustomImage = {
    id: string
    team_id: number
    status: string
    version: number
    base_image_reference: string | null
    base_image_refresh_reference: string | null
    has_published_image: boolean
    has_error: boolean
    has_spec: boolean
    updated_at: string
    workflow_url: string
}
export type Workflow = {
    status: string
    workflow_id?: string
    run_id?: string | null
    started_at?: string | null
    closed_at?: string | null
    url: string
    activities: { name: string; state: string; attempt: number }[]
}
export type SourceData = {
    package: { version: string; revision: string | null }
    release: {
        pin: string
        runs_error?: string | null
        runs_stale?: boolean
        runs_observed_at?: string | null
        runs: {
            id: number
            head_sha: string
            status: string
            conclusion: string | null
            html_url: string
            created_at: string
            build_jobs: { name: string; status: string; conclusion: string | null; promotion: string | null }[]
            build_jobs_error?: string | null
        }[]
    }
    custom: { images: CustomImage[]; truncated: boolean; limit: number }
    dev_stack: {
        name: string
        base_image_reference: string | null
        workflow_url: string
        protected?: boolean
        attempt_id?: string | null
        workflow_run_id?: string | null
        auto_refresh?: boolean
        observation_error?: string
        status?:
            | 'disabled'
            | 'blocked'
            | 'retry_scheduled'
            | 'current'
            | 'queued'
            | 'building'
            | 'verifying'
            | 'failed'
            | 'superseded'
        generation?: number
        active_generation?: number
        active_image_id?: string | null
        active_agent_version?: string | null
        desired_base_reference?: string | null
        repository_sha?: string | null
        activated_at?: string | null
        requested_at?: string | null
        target_observed_at?: string | null
        next_retry_at?: string | null
        reason?: string
        attempt_started_at?: string | null
        lease_expires_at?: string | null
        deadline_at?: string | null
    }
} & Record<ImageName, RegistryImage>
export type Sources = { [K in keyof SourceData]?: Source<SourceData[K]> }
export const sourceNames: (keyof SourceData)[] = ['package', 'release', ...imageNames, 'custom', 'dev_stack']
export const labels: Record<Evidence, string> = {
    current: 'Current',
    waiting: 'Awaiting refresh',
    building: 'Building',
    failed: 'Failed',
    unknown: 'Unverified',
    unmanaged: 'Not eligible',
}
export const variants = {
    current: 'success',
    waiting: 'warning',
    building: 'info',
    failed: 'destructive',
    unknown: 'default',
    unmanaged: 'default',
} as const

export type ReleaseBadge = { label: string; variant: (typeof variants)[Evidence] }

export function fresh(source: Source<unknown> | undefined, now = Date.now()): boolean {
    return source?.status === 'ok' && !!source.observed_at && now - Date.parse(source.observed_at) < 150_000
}

export function releaseBadge(sources: Sources, name: 'package' | 'release' | ImageName): ReleaseBadge | undefined {
    const platforms = imageNames.includes(name as ImageName) ? sources[name as ImageName]?.data?.platforms : undefined
    const versions =
        name === 'package'
            ? [sources.package?.data?.version]
            : name === 'release'
              ? [sources.release?.data?.pin]
              : (platforms || []).map((platform) => platform.version)
    if (!versions.some(Boolean)) {
        return undefined
    }
    if (name === 'package') {
        return fresh(sources.package)
            ? { label: 'Latest release', variant: 'success' }
            : { label: 'Last seen', variant: 'default' }
    }
    const latest = sources.package?.data?.version
    if (
        !latest ||
        versions.some((version) => !version) ||
        (platforms && !['amd64', 'arm64'].every((arch) => platforms.some((platform) => platform.arch === arch)))
    ) {
        return { label: 'Last seen', variant: 'default' }
    }
    const matches = versions.every((version) => version === latest)
    if (!fresh(sources[name]) || !fresh(sources.package)) {
        return {
            label: matches ? 'Last seen · matches latest' : 'Last seen · differs from latest',
            variant: matches ? 'default' : 'warning',
        }
    }
    return {
        label: matches ? 'Latest release' : 'Different release',
        variant: matches ? 'success' : 'warning',
    }
}

export function pinState(sources: Sources): Evidence {
    if (
        !fresh(sources.package) ||
        !fresh(sources.release) ||
        !sources.package?.data?.version ||
        !sources.release?.data?.pin
    ) {
        return 'unknown'
    }
    return sources.package.data.version === sources.release.data.pin ? 'current' : 'waiting'
}

export function imageState(sources: Sources, name: ImageName): Evidence {
    const source = sources[name]
    if (!fresh(source) || !fresh(sources.release) || !source?.data || !sources.release?.data) {
        return 'unknown'
    }
    const platforms = source.data.platforms
    if (
        !['amd64', 'arm64'].every((arch) =>
            platforms.some((p) => p.arch === arch && p.version === sources.release?.data?.pin)
        )
    ) {
        return 'waiting'
    }
    if (name !== 'base') {
        if (!fresh(sources.base) || !sources.base?.data) {
            return 'unknown'
        }
        if (
            !platforms.every((p) => {
                const base = sources.base?.data?.platforms.find((b) => b.arch === p.arch)
                return (
                    !!base?.revision &&
                    !!base.inputs_digest &&
                    p.base_revision === base.revision &&
                    p.inputs_digest === base.inputs_digest
                )
            })
        ) {
            return 'waiting'
        }
    }
    return 'current'
}

export function devStackState(sources: Sources): Evidence {
    const reference = sources.dev_stack?.data?.base_image_reference
    const base = sources.vm?.data?.reference
    if (!fresh(sources.dev_stack) || !fresh(sources.vm) || !reference || !base) {
        return 'unknown'
    }
    return reference === base ? 'current' : 'waiting'
}

export function devStackBadge(sources: Sources): ReleaseBadge {
    if (sources.dev_stack?.data && !fresh(sources.dev_stack)) {
        return { label: 'Last seen', variant: 'default' }
    }
    const state = devStackState(sources)
    if (sources.dev_stack?.data?.protected) {
        return {
            label: state === 'current' ? 'Base current' : state === 'waiting' ? 'Base behind' : 'Base unknown',
            variant: variants[state],
        }
    }
    return { label: labels[state], variant: variants[state] }
}

export function devStackProgress(sources: Sources, now = Date.now()): ReleaseBadge | undefined {
    const data = sources.dev_stack?.data
    if (!data?.protected || !fresh(sources.dev_stack, now)) {
        return undefined
    }
    if (data.status === 'disabled') {
        return { label: 'Baking disabled', variant: 'default' }
    }
    if (data.status === 'blocked') {
        return { label: 'Blocked', variant: 'destructive' }
    }
    if (data.status === 'retry_scheduled') {
        return { label: 'Retry scheduled', variant: 'warning' }
    }
    if (
        ['building', 'verifying'].includes(data.status || '') &&
        (!data.lease_expires_at ||
            Date.parse(data.lease_expires_at) <= Date.parse(sources.dev_stack!.observed_at!) ||
            !data.deadline_at ||
            Date.parse(data.deadline_at) <= now)
    ) {
        return { label: 'Recovery pending', variant: 'warning' }
    }
    if (data.status === 'building') {
        return { label: devStackState(sources) === 'current' ? 'Rebuilding' : 'Building', variant: 'info' }
    }
    if (data.status === 'verifying') {
        return { label: 'Verifying', variant: 'info' }
    }
    if (data.status === 'current') {
        return { label: 'Active', variant: 'success' }
    }
    if (data.status === 'failed') {
        return { label: 'Failed', variant: 'destructive' }
    }
    return { label: data.status === 'superseded' ? 'Superseded' : 'Queued', variant: 'default' }
}

export function selectedWorkflow(
    selected: string,
    sources: Sources,
    workflow: { id: string; source: Source<Workflow> } | null
): Source<Workflow> | null {
    if (workflow?.id !== selected) {
        return null
    }
    const devStack = sources.dev_stack?.data
    if (
        selected === 'dev_stack' &&
        devStack?.protected &&
        (!devStack.attempt_id ||
            workflow.source.data?.workflow_id !== `activate-dev-stack-image-${devStack.attempt_id}` ||
            (devStack.workflow_run_id && workflow.source.data?.run_id !== devStack.workflow_run_id))
    ) {
        return null
    }
    return workflow.source
}

export function customState(image: CustomImage, currentBase: string | undefined): Evidence {
    if (['building', 'scanning'].includes(image.status)) {
        return 'building'
    }
    if (['build_failed', 'scan_failed'].includes(image.status)) {
        return 'failed'
    }
    if (image.status !== 'ready' || !image.has_published_image || !image.has_spec) {
        return 'unmanaged'
    }
    if (!currentBase || !image.base_image_reference) {
        return 'unknown'
    }
    if (image.base_image_reference === currentBase) {
        return 'current'
    }
    return image.has_error ? 'failed' : 'waiting'
}
