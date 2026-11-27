import { ApiError } from 'lib/api-error'

import { aeoBrandsCreate, aeoBrandsList, aeoBrandsPartialUpdate } from '../generated/api'
import type { AEOBrandApi } from '../generated/api.schemas'
import { saveBrand } from './brandCatalog'

jest.mock('../generated/api', () => ({
    aeoBrandsCreate: jest.fn(),
    aeoBrandsList: jest.fn(),
    aeoBrandsPartialUpdate: jest.fn(async () => ({})),
}))

const brand = (id: string, domain: string): AEOBrandApi => ({ id, domain }) as AEOBrandApi

describe('saveBrand', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.mocked(aeoBrandsCreate).mockRejectedValue(new ApiError('Already in the catalog', 400))
    })

    it.each([
        ['the same domain', 'https://www.example.com/pricing', 'apex'],
        ['a subdomain the API stores as its registrable domain', 'docs.example.com', 'apex'],
        ['the most specific cataloged domain', 'eu.app.example.com', 'app'],
    ])('relabels the cataloged brand a clash points to: %s', async (_name, input, expected) => {
        jest.mocked(aeoBrandsList).mockResolvedValue({
            count: 3,
            results: [brand('apex', 'example.com'), brand('app', 'app.example.com'), brand('other', 'notexample.com')],
        } as Awaited<ReturnType<typeof aeoBrandsList>>)

        await saveBrand('1', input, 'competitor')

        expect(aeoBrandsPartialUpdate).toHaveBeenCalledWith('1', expected, { kind: 'competitor', status: 'confirmed' })
    })

    it('fails when no cataloged brand explains the clash', async () => {
        jest.mocked(aeoBrandsList).mockResolvedValue({
            count: 1,
            results: [brand('other', 'notexample.com')],
        } as Awaited<ReturnType<typeof aeoBrandsList>>)

        await expect(saveBrand('1', 'example.com', 'own')).rejects.toBeInstanceOf(ApiError)
        expect(aeoBrandsPartialUpdate).not.toHaveBeenCalled()
    })
})
