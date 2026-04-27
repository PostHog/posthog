import { describe, expect, it } from 'vitest'

import { TypeReader } from '../src/lib/type-reader'

const SDK_DTS = `
export namespace Schemas {
    export interface Pet {
        id: number
        name: string
        tag?: PetTag
    }

    export interface PetTag {
        label?: string
    }

    export interface PaginatedPetList {
        count?: number
        results?: Pet[]
    }
}

export interface PetsListInput {
    query?: {
        limit?: number
    }
}

export interface PetsRetrieveInput {
    path: {
        id: number
    }
}

export interface Client {
    petsList(input: PetsListInput): Promise<Schemas.PaginatedPetList>
    petsRetrieve(input: PetsRetrieveInput): Promise<Schemas.Pet>
}
`.trim()

describe('TypeReader', () => {
    const reader = new TypeReader(SDK_DTS)

    it('reads a Schemas type and inlines its one-deep refs', () => {
        const result = reader.read('type', 'Pet')
        expect(result).not.toBeNull()
        expect(result!.source).toContain('interface Pet')
        // Pet refs PetTag → should be inlined
        expect(result!.source).toContain('interface PetTag')
    })

    it('reads an operation method, its Input interface, and the response type', () => {
        const result = reader.read('operation', 'petsRetrieve')
        expect(result).not.toBeNull()
        expect(result!.source).toContain('petsRetrieve(')
        expect(result!.source).toContain('PetsRetrieveInput')
        // Response type Pet should be present
        expect(result!.source).toContain('interface Pet')
    })

    it('returns null for unknown names', () => {
        expect(reader.read('type', 'DoesNotExist')).toBeNull()
        expect(reader.read('operation', 'doesNotExist')).toBeNull()
    })
})
