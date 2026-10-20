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

export function readyImages(images: SandboxCustomImageDTOApi[] | null): SandboxCustomImageDTOApi[] | null {
    return images === null ? null : images.filter((image) => image.status === 'ready')
}

export function standaloneReadyImages(
    images: SandboxCustomImageDTOApi[] | null,
    environments: SandboxEnvironmentDTOApi[] | null
): SandboxCustomImageDTOApi[] {
    const attached = new Set((environments ?? []).flatMap((environment) => environment.custom_image_id ?? []))
    return (images ?? []).filter((image) => image.status === 'ready' && !attached.has(image.id))
}

export type CloudTargetAvailability = 'available' | 'missing' | 'unknown'

export function cloudTargetAvailability(
    key: string | null,
    environments: SandboxEnvironmentDTOApi[] | null,
    images: SandboxCustomImageDTOApi[] | null
): CloudTargetAvailability {
    const { sandbox_environment_id, custom_image_id } = cloudTargetIds(key)
    const [list, id] = sandbox_environment_id
        ? [environments, sandbox_environment_id]
        : custom_image_id
          ? [images, custom_image_id]
          : [[], null]
    if (list === null) {
        return 'unknown'
    }
    return list.some((target) => target.id === id) ? 'available' : 'missing'
}
