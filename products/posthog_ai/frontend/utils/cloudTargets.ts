import type { SandboxCustomImageDTOApi, SandboxEnvironmentDTOApi } from 'products/tasks/frontend/generated/api.schemas'

export interface CloudTargetIds {
    sandbox_environment_id?: string
    custom_image_id?: string
}

export function cloudTargetKey(kind: 'environment' | 'image', id: string): string {
    return `${kind}:${id}`
}

export function cloudTargetIds(key: string | null): CloudTargetIds {
    const [kind, id] = key?.split(':') ?? []
    if (kind === 'environment' && id) {
        return { sandbox_environment_id: id }
    }
    if (kind === 'image' && id) {
        return { custom_image_id: id }
    }
    return {}
}

export function unattachedImages(
    images: SandboxCustomImageDTOApi[] | null,
    environments: SandboxEnvironmentDTOApi[] | null,
    keep: (string | null)[]
): SandboxCustomImageDTOApi[] {
    const attached = new Set((environments ?? []).flatMap((environment) => environment.custom_image_id ?? []))
    return (images ?? []).filter((image) => !attached.has(image.id) || keep.includes(cloudTargetKey('image', image.id)))
}

export function isMissingCloudTarget(
    key: string,
    environments: SandboxEnvironmentDTOApi[] | null,
    images: SandboxCustomImageDTOApi[] | null
): boolean {
    const { sandbox_environment_id, custom_image_id } = cloudTargetIds(key)
    const list = sandbox_environment_id ? environments : custom_image_id ? images : []
    return list !== null && !list.some((target) => target.id === (sandbox_environment_id ?? custom_image_id))
}
