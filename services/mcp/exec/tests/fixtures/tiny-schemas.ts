// Mirrors what services/mcp/src/api/generated.ts looks like, in miniature.
// Used by tests as a stand-in for the real Schemas namespace.
export const TINY_SCHEMAS_NAMESPACE_SOURCE = `
export namespace Schemas {
    /**
     * A pet with a name and optional tag.
     */
    export interface Pet {
        id: number
        name: string
        tag?: PetTag
    }

    /**
     * A label attached to a pet.
     */
    export interface PetTag {
        label?: string
    }

    /**
     * Paginated list of pets.
     */
    export interface PaginatedPetList {
        count?: number
        results?: Pet[]
    }
}
`.trim()
