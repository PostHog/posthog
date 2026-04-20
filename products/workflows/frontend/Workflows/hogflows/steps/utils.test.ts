import { updateItemWithOptionalName, updateOptionalName } from './utils'

describe('utils', () => {
    describe('updateOptionalName', () => {
        it('should add name when value is provided', () => {
            const obj = { id: '1', filters: {} }
            const result = updateOptionalName(obj, 'Custom Name')

            expect(result).toEqual({
                id: '1',
                filters: {},
                name: 'Custom Name',
            })
        })

        it('should update existing name when new value is provided', () => {
            const obj = { id: '1', filters: {}, name: 'Old Name' }
            const result = updateOptionalName(obj, 'New Name')

            expect(result).toEqual({
                id: '1',
                filters: {},
                name: 'New Name',
            })
        })

        it('should remove name when value is empty string', () => {
            const obj = { id: '1', filters: {}, name: 'Existing Name' }
            const result = updateOptionalName(obj, '')

            expect(result).toEqual({
                id: '1',
                filters: {},
            })
            expect('name' in result).toBe(false)
        })

        it('should remove name when value is undefined', () => {
            const obj = { id: '1', filters: {}, name: 'Existing Name' }
            const result = updateOptionalName(obj, undefined)

            expect(result).toEqual({
                id: '1',
                filters: {},
            })
            expect('name' in result).toBe(false)
        })

        it('should preserve other properties', () => {
            const obj = {
                id: '1',
                filters: { test: true },
                otherProp: 'value',
                nested: { deep: 'object' },
            }
            const result = updateOptionalName(obj, 'Name')

            expect(result).toEqual({
                id: '1',
                filters: { test: true },
                otherProp: 'value',
                nested: { deep: 'object' },
                name: 'Name',
            })
        })
    })

    describe('updateItemWithOptionalName', () => {
        it('should update name at specified index', () => {
            const items = [
                { id: '1', filters: {} },
                { id: '2', filters: {} },
                { id: '3', filters: {} },
            ]
            const result = updateItemWithOptionalName(items, 1, 'Middle Item')

            expect(result).toEqual([
                { id: '1', filters: {} },
                { id: '2', filters: {}, name: 'Middle Item' },
                { id: '3', filters: {} },
            ])
        })

        it('should remove name at specified index when value is empty', () => {
            const items = [
                { id: '1', filters: {}, name: 'First' },
                { id: '2', filters: {}, name: 'Second' },
                { id: '3', filters: {}, name: 'Third' },
            ]
            const result = updateItemWithOptionalName(items, 1, '')

            expect(result).toEqual([
                { id: '1', filters: {}, name: 'First' },
                { id: '2', filters: {} },
                { id: '3', filters: {}, name: 'Third' },
            ])
            expect('name' in result[1]).toBe(false)
        })

        it('should only modify the item at the specified index', () => {
            const items = [
                { id: '1', filters: {}, name: 'First' },
                { id: '2', filters: {} },
                { id: '3', filters: {}, name: 'Third' },
            ]
            const result = updateItemWithOptionalName(items, 1, 'Second')

            expect(result[0]).toEqual({ id: '1', filters: {}, name: 'First' })
            expect(result[1]).toEqual({ id: '2', filters: {}, name: 'Second' })
            expect(result[2]).toEqual({ id: '3', filters: {}, name: 'Third' })
        })

        it('should handle index out of bounds gracefully', () => {
            const items = [
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ]
            const result = updateItemWithOptionalName(items, 5, 'Out of bounds')

            expect(result).toEqual([
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ])
        })

        it('should handle negative index gracefully', () => {
            const items = [
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ]
            const result = updateItemWithOptionalName(items, -1, 'Negative')

            expect(result).toEqual([
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ])
        })

        it('should return a new array (immutability)', () => {
            const items = [
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ]
            const result = updateItemWithOptionalName(items, 0, 'First')

            expect(result).not.toBe(items)
            expect(items[0]).toEqual({ id: '1', filters: {} }) // Original unchanged
        })

        it('should return new objects for modified items (deep immutability)', () => {
            const items = [
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ]
            const result = updateItemWithOptionalName(items, 0, 'First')

            expect(result[0]).not.toBe(items[0]) // Modified item is new
            expect(result[1]).toBe(items[1]) // Unmodified item is same reference
        })

        it('should handle empty array', () => {
            const items: Array<{ filters: {}; name?: string }> = []
            const result = updateItemWithOptionalName(items, 0, 'Name')

            expect(result).toEqual([])
        })
    })
})
