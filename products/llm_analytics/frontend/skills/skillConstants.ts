export const SKILL_NAME_MAX_LENGTH = 64
export const SKILL_DESCRIPTION_MAX_LENGTH = 4096

export function validateSkillName(name: string): string | undefined {
    if (!name?.trim()) {
        return 'Name is required'
    }
    if (name.toLowerCase() === 'new') {
        return "'new' is a reserved name"
    }
    if (name.length > SKILL_NAME_MAX_LENGTH) {
        return `Name must be ${SKILL_NAME_MAX_LENGTH} characters or fewer`
    }
    if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(name)) {
        return 'Lowercase letters, numbers, and hyphens only'
    }
    if (name.includes('--')) {
        return 'Consecutive hyphens are not allowed'
    }
    return undefined
}
