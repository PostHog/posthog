import { parseJsonPickleVariable } from './serde'

describe('parseJsonPickleVariable', () => {
    describe('simple types', () => {
        it('should parse null', () => {
            const result = parseJsonPickleVariable('null')
            expect(result).toEqual({
                type: 'simple',
                value: null,
            })
        })

        it('should parse boolean true', () => {
            const result = parseJsonPickleVariable('true')
            expect(result).toEqual({
                type: 'simple',
                value: true,
            })
        })

        it('should parse boolean false', () => {
            const result = parseJsonPickleVariable('false')
            expect(result).toEqual({
                type: 'simple',
                value: false,
            })
        })

        it('should parse integer numbers', () => {
            const result = parseJsonPickleVariable('42')
            expect(result).toEqual({
                type: 'simple',
                value: 42,
            })
        })

        it('should parse float numbers', () => {
            const result = parseJsonPickleVariable('3.14159')
            expect(result).toEqual({
                type: 'simple',
                value: 3.14159,
            })
        })

        it('should parse negative numbers', () => {
            const result = parseJsonPickleVariable('-123')
            expect(result).toEqual({
                type: 'simple',
                value: -123,
            })
        })

        it('should parse simple strings', () => {
            const result = parseJsonPickleVariable('"hello world"')
            expect(result).toEqual({
                type: 'simple',
                value: 'hello world',
            })
        })

        it('should parse empty strings', () => {
            const result = parseJsonPickleVariable('""')
            expect(result).toEqual({
                type: 'simple',
                value: '',
            })
        })
    })

    describe('complex types without metadata', () => {
        it('should parse simple arrays', () => {
            const result = parseJsonPickleVariable('[1, 2, 3]')
            expect(result).toEqual({
                type: 'complex',
                value: [1, 2, 3],
                typeName: undefined,
            })
        })

        it('should parse empty arrays', () => {
            const result = parseJsonPickleVariable('[]')
            expect(result).toEqual({
                type: 'complex',
                value: [],
                typeName: undefined,
            })
        })

        it('should parse simple objects', () => {
            const result = parseJsonPickleVariable('{"name": "Alice", "age": 30}')
            expect(result).toEqual({
                type: 'complex',
                value: { name: 'Alice', age: 30 },
                typeName: undefined,
            })
        })

        it('should parse empty objects', () => {
            const result = parseJsonPickleVariable('{}')
            expect(result).toEqual({
                type: 'complex',
                value: {},
                typeName: undefined,
            })
        })

        it('should parse nested objects', () => {
            const result = parseJsonPickleVariable('{"user": {"name": "Bob", "settings": {"theme": "dark"}}}')
            expect(result).toEqual({
                type: 'complex',
                value: {
                    user: {
                        name: 'Bob',
                        settings: {
                            theme: 'dark',
                        },
                    },
                },
                typeName: undefined,
            })
        })

        it('should parse arrays with mixed types', () => {
            const result = parseJsonPickleVariable('[1, "text", true, null, {"key": "value"}]')
            expect(result).toEqual({
                type: 'complex',
                value: [1, 'text', true, null, { key: 'value' }],
                typeName: undefined,
            })
        })
    })

    describe('jsonpickle metadata handling', () => {
        it('should extract py/object type name', () => {
            const result = parseJsonPickleVariable('{"py/object": "posthog.models.User", "name": "Alice"}')
            expect(result).toEqual({
                type: 'complex',
                value: { name: 'Alice' },
                typeName: 'posthog.models.User',
            })
        })

        it('should remove all py/ prefixed keys', () => {
            const result = parseJsonPickleVariable(
                JSON.stringify({
                    'py/object': 'SomeClass',
                    'py/id': 123,
                    'py/state': 'active',
                    name: 'Test',
                    value: 42,
                })
            )
            expect(result).toEqual({
                type: 'complex',
                value: {
                    name: 'Test',
                    value: 42,
                },
                typeName: 'SomeClass',
            })
        })

        it('should clean metadata from nested objects', () => {
            const result = parseJsonPickleVariable(
                JSON.stringify({
                    'py/object': 'Parent',
                    child: {
                        'py/object': 'Child',
                        'py/ref': 1,
                        name: 'Nested',
                    },
                    items: [
                        {
                            'py/object': 'Item',
                            value: 1,
                        },
                    ],
                })
            )
            expect(result).toEqual({
                type: 'complex',
                value: {
                    child: {
                        name: 'Nested',
                    },
                    items: [
                        {
                            value: 1,
                        },
                    ],
                },
                typeName: 'Parent',
            })
        })

        it('should clean metadata from arrays of objects', () => {
            const result = parseJsonPickleVariable(
                JSON.stringify([
                    { 'py/object': 'Item1', name: 'First' },
                    { 'py/object': 'Item2', name: 'Second' },
                ])
            )
            expect(result).toEqual({
                type: 'complex',
                value: [{ name: 'First' }, { name: 'Second' }],
                typeName: undefined,
            })
        })

        it('should preserve keys that contain py/ but do not start with it', () => {
            const result = parseJsonPickleVariable('{"python_version": "3.9", "py/object": "Test"}')
            expect(result).toEqual({
                type: 'complex',
                value: { python_version: '3.9' },
                typeName: 'Test',
            })
        })
    })

    describe('already parsed values (non-strings)', () => {
        it('should handle already parsed numbers', () => {
            const result = parseJsonPickleVariable(42)
            expect(result).toEqual({
                type: 'simple',
                value: 42,
            })
        })

        it('should handle already parsed booleans', () => {
            const result = parseJsonPickleVariable(true)
            expect(result).toEqual({
                type: 'simple',
                value: true,
            })
        })

        it('should handle already parsed null', () => {
            const result = parseJsonPickleVariable(null)
            expect(result).toEqual({
                type: 'simple',
                value: null,
            })
        })

        it('should handle already parsed objects', () => {
            const obj = { name: 'Test', value: 123 }
            const result = parseJsonPickleVariable(obj)
            expect(result).toEqual({
                type: 'complex',
                value: obj,
            })
        })

        it('should handle already parsed arrays', () => {
            const arr = [1, 2, 3]
            const result = parseJsonPickleVariable(arr)
            expect(result).toEqual({
                type: 'complex',
                value: arr,
            })
        })
    })

    describe('invalid JSON handling', () => {
        it('should treat invalid JSON as simple string', () => {
            const result = parseJsonPickleVariable('not valid json')
            expect(result).toEqual({
                type: 'simple',
                value: 'not valid json',
            })
        })

        it('should handle malformed JSON objects', () => {
            const result = parseJsonPickleVariable('{name: "missing quotes"}')
            expect(result).toEqual({
                type: 'simple',
                value: '{name: "missing quotes"}',
            })
        })

        it('should handle truncated JSON', () => {
            const result = parseJsonPickleVariable('{"incomplete": ')
            expect(result).toEqual({
                type: 'simple',
                value: '{"incomplete": ',
            })
        })
    })

    describe('edge cases', () => {
        it('should handle empty string', () => {
            const result = parseJsonPickleVariable('')
            expect(result).toEqual({
                type: 'simple',
                value: '',
            })
        })

        it('should handle deeply nested structures', () => {
            const deeplyNested = {
                'py/object': 'Level1',
                level2: {
                    'py/object': 'Level2',
                    level3: {
                        'py/object': 'Level3',
                        level4: {
                            'py/ref': 999,
                            data: 'deep',
                        },
                    },
                },
            }
            const result = parseJsonPickleVariable(JSON.stringify(deeplyNested))
            expect(result).toEqual({
                type: 'complex',
                value: {
                    level2: {
                        level3: {
                            level4: {
                                data: 'deep',
                            },
                        },
                    },
                },
                typeName: 'Level1',
            })
        })

        it('should handle objects with only metadata keys', () => {
            const result = parseJsonPickleVariable('{"py/object": "EmptyClass", "py/id": 1}')
            expect(result).toEqual({
                type: 'complex',
                value: {},
                typeName: 'EmptyClass',
            })
        })

        it('should handle unicode strings', () => {
            const result = parseJsonPickleVariable('"Hello 世界 🌍"')
            expect(result).toEqual({
                type: 'simple',
                value: 'Hello 世界 🌍',
            })
        })

        it('should handle special characters in strings', () => {
            const result = parseJsonPickleVariable('"Line 1\\nLine 2\\tTabbed"')
            expect(result).toEqual({
                type: 'simple',
                value: 'Line 1\nLine 2\tTabbed',
            })
        })

        it('should handle large numbers', () => {
            const result = parseJsonPickleVariable('9007199254740991')
            expect(result).toEqual({
                type: 'simple',
                value: 9007199254740991,
            })
        })
    })

    describe('real-world jsonpickle examples', () => {
        it('should parse a typical Django model instance', () => {
            const djangoModel = {
                'py/object': 'posthog.models.User',
                'py/id': 42,
                id: 123,
                email: 'user@example.com',
                is_active: true,
                created_at: '2024-01-01T00:00:00Z',
            }
            const result = parseJsonPickleVariable(JSON.stringify(djangoModel))
            expect(result).toEqual({
                type: 'complex',
                value: {
                    id: 123,
                    email: 'user@example.com',
                    is_active: true,
                    created_at: '2024-01-01T00:00:00Z',
                },
                typeName: 'posthog.models.User',
            })
        })

        it('should parse a list of model instances', () => {
            const modelList = [
                {
                    'py/object': 'posthog.models.Event',
                    'py/id': 1,
                    event: 'pageview',
                    distinct_id: 'user1',
                },
                {
                    'py/object': 'posthog.models.Event',
                    'py/id': 2,
                    event: 'click',
                    distinct_id: 'user2',
                },
            ]
            const result = parseJsonPickleVariable(JSON.stringify(modelList))
            expect(result).toEqual({
                type: 'complex',
                value: [
                    {
                        event: 'pageview',
                        distinct_id: 'user1',
                    },
                    {
                        event: 'click',
                        distinct_id: 'user2',
                    },
                ],
                typeName: undefined,
            })
        })

        it('should parse datetime objects with timezone info', () => {
            const datetimeObj = {
                'py/object': 'datetime.datetime',
                'py/reduce': [{ 'py/type': 'datetime.datetime' }, ['2024', '01', '15', '10', '30', '45']],
                __value__: '2024-01-15T10:30:45',
            }
            const result = parseJsonPickleVariable(JSON.stringify(datetimeObj))
            expect(result.type).toBe('complex')
            expect(result.typeName).toBe('datetime.datetime')
            expect(result.value.__value__).toBe('2024-01-15T10:30:45')
        })
    })
})
