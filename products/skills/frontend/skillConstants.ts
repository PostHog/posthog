export const SKILL_NAME_MAX_LENGTH = 64
export const SKILL_DESCRIPTION_MAX_LENGTH = 4096

// Names that collide with reserved /skills routes: 'new' (the create form) and the category-tab
// slugs registered under /skills/<slug> in manifest.tsx. A skill with one of these names would be
// shadowed by its route. Kept in sync with RESERVED_SKILL_NAMES in the backend skill_serializers.
const RESERVED_SKILL_NAMES = new Set(['new', 'scouts'])

export function validateSkillName(name: string): string | undefined {
    if (!name?.trim()) {
        return 'Name is required'
    }
    if (RESERVED_SKILL_NAMES.has(name.toLowerCase())) {
        return `'${name.toLowerCase()}' is a reserved name`
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
