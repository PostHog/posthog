import type { SandboxCustomImageDTOApi, SandboxEnvironmentDTOApi } from 'products/tasks/frontend/generated/api.schemas'

export type CloudTargetKind = 'environment' | 'image'

export interface CloudTargetIds {
    sandbox_environment_id?: string
    custom_image_id?: string
}

export function cloudTargetKey(kind: CloudTargetKind, id: string): string {
    return `${kind}:${id}`
}

export function cloudTargetIds(key: string | null): CloudTargetIds {
    const [kind, id] = key?.split(':') ?? []
    if (!id) {
        return {}
    }
    if (kind === 'environment') {
        return { sandbox_environment_id: id }
    }
    if (kind === 'image') {
        return { custom_image_id: id }
    }
    return {}
}

export function standaloneReadyImages(
    images: SandboxCustomImageDTOApi[] | null,
    environments: SandboxEnvironmentDTOApi[] | null
): SandboxCustomImageDTOApi[] {
    const attached = new Set((environments ?? []).flatMap((environment) => environment.custom_image_id ?? []))
    return (images ?? []).filter((image) => image.status === 'ready' && !attached.has(image.id))
}

export function isAvailableCloudTarget(
    key: string | null,
    environments: SandboxEnvironmentDTOApi[] | null,
    images: SandboxCustomImageDTOApi[] | null
): boolean {
    const { sandbox_environment_id, custom_image_id } = cloudTargetIds(key)
    if (sandbox_environment_id) {
        return !!environments?.some((environment) => environment.id === sandbox_environment_id)
    }
    if (custom_image_id) {
        return !!images?.some((image) => image.id === custom_image_id)
    }
    return false
}
