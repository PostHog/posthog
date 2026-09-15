export const SKILL_NAME_MAX_LENGTH = 64
// The Agent Skills spec (https://agentskills.io/specification) caps description at 1024. Writes
// use that cap so a skill cannot grow past what community publish and export accept. Kept in sync
// with the description serializer field and SPEC_DESCRIPTION_MAX_LENGTH in the backend.
export const SKILL_DESCRIPTION_MAX_LENGTH = 1024
// Kept in sync with MAX_SKILL_FILE_BYTES and MAX_SKILL_FILE_COUNT in the backend skill_serializers.
export const SKILL_FILE_MAX_BYTES = 1_000_000
export const SKILL_FILE_MAX_COUNT = 200
// Kept in sync with MAX_SKILL_OWNERS in the backend skill_serializers.
export const SKILL_OWNER_MAX_COUNT = 25

// Name prefixes that Signals and ReviewHog key their own per-skill settings on, so a skill cannot
// be renamed into or out of one. Kept in sync with CATEGORY_BY_NAME_PREFIX in the backend
// products/skills/backend/models/skills.py.
export const PRODUCT_OWNED_SKILL_NAME_PREFIXES = ['signals-scout-', 'review-hog-']

// Names that collide with reserved /skills routes: 'new' (the create form) and the tab slugs
// registered under /skills/<slug> in manifest.tsx. A skill with one of these names would be
// shadowed by its route. Kept in sync with RESERVED_SKILL_NAMES in the backend skill_serializers.
const RESERVED_SKILL_NAMES = new Set(['new', 'scouts', 'review-hog', 'community'])

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
