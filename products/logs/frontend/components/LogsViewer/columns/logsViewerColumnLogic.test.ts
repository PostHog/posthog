import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { ParsedLogMessage } from '../../../types'
import { BODY_COLUMN, DEFAULT_CONFIGURABLE_COLUMNS_BY_ID, FIXED_COLUMNS_BY_ID, TIMESTAMP_COLUMN } from './constants'
import { logsViewerColumnLogic } from './logsViewerColumnLogic'
import { AttributeColumn, ConfigurableColumn, ExpressionColumn } from './types'

describe('logsViewerColumnLogic', () => {
    let logic: ReturnType<typeof logsViewerColumnLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = logsViewerColumnLogic({ id: 'test-tab' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('initial state', () => {
        it('has default configurable columns', () => {
            expect(logic.values.configurableColumnsById).toEqual(DEFAULT_CONFIGURABLE_COLUMNS_BY_ID)
        })

        it('merges fixed and configurable columns in columnsById', () => {
            expect(logic.values.columnsById).toEqual({
                ...FIXED_COLUMNS_BY_ID,
                ...DEFAULT_CONFIGURABLE_COLUMNS_BY_ID,
            })
        })
    })

    describe('setConfigurableColumns', () => {
        it('replaces all configurable columns', async () => {
            const newColumns: Record<string, ConfigurableColumn> = {
                timestampColumn: { ...TIMESTAMP_COLUMN, width: 200 },
            }

            await expectLogic(logic, () => {
                logic.actions.setConfigurableColumns(newColumns)
            }).toMatchValues({
                configurableColumnsById: newColumns,
            })
        })
    })

    describe('setColumnWidth', () => {
        it('updates width for existing column', async () => {
            await expectLogic(logic, () => {
                logic.actions.setColumnWidth('timestampColumn', 250)
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById.timestampColumn.width).toBe(250)
        })

        it('ignores non-existent column', async () => {
            const before = { ...logic.values.configurableColumnsById }

            await expectLogic(logic, () => {
                logic.actions.setColumnWidth('nonExistentColumn', 100)
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById).toEqual(before)
        })
    })

    describe('addAttributeColumn', () => {
        it('adds new attribute column with correct properties', async () => {
            await expectLogic(logic, () => {
                logic.actions.addAttributeColumn('service.name')
            }).toFinishAllListeners()

            const column = logic.values.configurableColumnsById['attribute-service.name'] as AttributeColumn
            expect(column).toBeTruthy()
            expect(column.type).toBe('attribute')
            expect(column.attributeKey).toBe('service.name')
            expect(column.label).toBe('service.name')
            expect(column.id).toBe('attribute-service.name')
        })

        it('assigns order after existing columns', async () => {
            await expectLogic(logic, () => {
                logic.actions.addAttributeColumn('first.attr')
            }).toFinishAllListeners()

            const firstOrder = logic.values.configurableColumnsById['attribute-first.attr'].order

            await expectLogic(logic, () => {
                logic.actions.addAttributeColumn('second.attr')
            }).toFinishAllListeners()

            const secondOrder = logic.values.configurableColumnsById['attribute-second.attr'].order
            expect(secondOrder).toBeGreaterThan(firstOrder!)
        })
    })

    describe('removeColumn', () => {
        it('removes existing column', async () => {
            logic.actions.addAttributeColumn('to.remove')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.configurableColumnsById['attribute-to.remove']).toBeTruthy()

            await expectLogic(logic, () => {
                logic.actions.removeColumn('attribute-to.remove')
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById['attribute-to.remove']).toBeUndefined()
        })

        it('handles removing non-existent column gracefully', async () => {
            const before = { ...logic.values.configurableColumnsById }

            await expectLogic(logic, () => {
                logic.actions.removeColumn('nonExistent')
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById).toEqual(before)
        })
    })

    describe('moveColumn', () => {
        beforeEach(async () => {
            logic.actions.setConfigurableColumns({
                col1: { id: 'col1', type: 'timestamp', order: 3, width: 100, label: 'Col 1' },
                col2: { id: 'col2', type: 'date', order: 4, width: 100, label: 'Col 2' },
                col3: { id: 'col3', type: 'time', order: 5, width: 100, label: 'Col 3' },
                bodyColumn: BODY_COLUMN,
            })
            await expectLogic(logic).toFinishAllListeners()
        })

        it('moves column left by swapping orders', async () => {
            await expectLogic(logic, () => {
                logic.actions.moveColumn('col2', 'left')
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById.col1.order).toBe(4)
            expect(logic.values.configurableColumnsById.col2.order).toBe(3)
        })

        it('moves column right by swapping orders', async () => {
            await expectLogic(logic, () => {
                logic.actions.moveColumn('col2', 'right')
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById.col2.order).toBe(5)
            expect(logic.values.configurableColumnsById.col3.order).toBe(4)
        })

        it('does nothing when moving first column left', async () => {
            const orderBefore = logic.values.configurableColumnsById.col1.order

            await expectLogic(logic, () => {
                logic.actions.moveColumn('col1', 'left')
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById.col1.order).toBe(orderBefore)
        })

        it('does nothing when moving last non-body column right', async () => {
            const orderBefore = logic.values.configurableColumnsById.col3.order

            await expectLogic(logic, () => {
                logic.actions.moveColumn('col3', 'right')
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById.col3.order).toBe(orderBefore)
        })

        it('does nothing for non-existent column', async () => {
            const before = { ...logic.values.configurableColumnsById }

            await expectLogic(logic, () => {
                logic.actions.moveColumn('nonExistent', 'left')
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById).toEqual(before)
        })
    })

    describe('columns selector', () => {
        it('sorts columns by order with body column always last', async () => {
            logic.actions.setConfigurableColumns({
                bodyColumn: { ...BODY_COLUMN, order: 1 },
                timestampColumn: { ...TIMESTAMP_COLUMN, order: 10 },
            })
            await expectLogic(logic).toFinishAllListeners()

            const columns = logic.values.columns
            const bodyIndex = columns.findIndex((c) => c.type === 'body')
            expect(bodyIndex).toBe(columns.length - 1)
        })

        it('includes both fixed and configurable columns', () => {
            const columnIds = logic.values.columns.map((c) => c.id)
            expect(columnIds).toContain('severityColorColumn')
            expect(columnIds).toContain('selectCheckboxColumn')
            expect(columnIds).toContain('timestampColumn')
            expect(columnIds).toContain('bodyColumn')
        })
    })

    describe('getColumnById', () => {
        it.each([
            ['fixed column', 'severityColorColumn'],
            ['configurable column', 'timestampColumn'],
        ])('returns %s by id', (_, columnId) => {
            const column = logic.values.getColumnById(columnId)
            expect(column).toBeTruthy()
            expect(column?.id).toBe(columnId)
        })

        it('returns undefined for non-existent column', () => {
            expect(logic.values.getColumnById('nonExistent')).toBeUndefined()
        })
    })

    describe('isAttributeColumn', () => {
        it('returns false when attribute column does not exist', () => {
            expect(logic.values.isAttributeColumn('some.attr')).toBe(false)
        })

        it('returns true when attribute column exists', async () => {
            logic.actions.addAttributeColumn('some.attr')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.isAttributeColumn('some.attr')).toBe(true)
        })
    })

    describe('sortedConfigurableColumns', () => {
        it('excludes body column from sorted list', () => {
            const sorted = logic.values.sortedConfigurableColumns
            expect(sorted.find((c) => c.type === 'body')).toBeUndefined()
        })

        it('returns columns sorted by order', async () => {
            logic.actions.setConfigurableColumns({
                col1: { id: 'col1', type: 'timestamp', order: 5, width: 100, label: 'Col 1' },
                col2: { id: 'col2', type: 'date', order: 3, width: 100, label: 'Col 2' },
                bodyColumn: BODY_COLUMN,
            })
            await expectLogic(logic).toFinishAllListeners()

            const sorted = logic.values.sortedConfigurableColumns
            expect(sorted[0].id).toBe('col2')
            expect(sorted[1].id).toBe('col1')
        })
    })

    describe('isFirstConfigurableColumn / isLastConfigurableColumn', () => {
        beforeEach(async () => {
            logic.actions.setConfigurableColumns({
                col1: { id: 'col1', type: 'timestamp', order: 3, width: 100, label: 'Col 1' },
                col2: { id: 'col2', type: 'date', order: 4, width: 100, label: 'Col 2' },
                bodyColumn: BODY_COLUMN,
            })
            await expectLogic(logic).toFinishAllListeners()
        })

        it('identifies first column correctly', () => {
            expect(logic.values.isFirstConfigurableColumn('col1')).toBe(true)
            expect(logic.values.isFirstConfigurableColumn('col2')).toBe(false)
        })

        it('identifies last column correctly', () => {
            expect(logic.values.isLastConfigurableColumn('col2')).toBe(true)
            expect(logic.values.isLastConfigurableColumn('col1')).toBe(false)
        })
    })

    describe('compiledPaths', () => {
        it('compiles expression paths for expression columns', async () => {
            const expressionColumn: ExpressionColumn = {
                id: 'expr1',
                type: 'expression',
                expression: 'attributes.http.status',
                width: 100,
            }
            logic.actions.setConfigurableColumns({
                expr1: expressionColumn,
                timestampColumn: TIMESTAMP_COLUMN,
            })
            await expectLogic(logic).toFinishAllListeners()

            const paths = logic.values.compiledPaths
            expect(paths.get('attributes.http.status')).toEqual(['attributes', 'http', 'status'])
        })

        it('ignores non-expression columns', async () => {
            logic.actions.setConfigurableColumns({
                timestampColumn: TIMESTAMP_COLUMN,
            })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.compiledPaths.size).toBe(0)
        })
    })

    describe('evaluateExpression', () => {
        const mockLog = {
            attributes: {
                http: {
                    status: 200,
                },
            },
            nested: {
                value: 'test',
            },
        } as unknown as ParsedLogMessage

        it.each([
            ['attributes.http.status', 200],
            ['nested.value', 'test'],
            ['nonexistent.path', undefined],
            ['attributes.http.nonexistent', undefined],
        ])('evaluates expression "%s" to %s', (expression, expected) => {
            expect(logic.values.evaluateExpression(mockLog, expression)).toBe(expected)
        })

        it('handles null values in path', () => {
            const logWithNull = { attributes: null } as unknown as ParsedLogMessage
            expect(logic.values.evaluateExpression(logWithNull, 'attributes.foo')).toBeUndefined()
        })
    })

    describe('toggleAttributeColumn listener', () => {
        it('adds column when it does not exist', async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleAttributeColumn('new.attr')
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById['attribute-new.attr']).toBeTruthy()
        })

        it('removes column when it exists', async () => {
            logic.actions.addAttributeColumn('existing.attr')
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.toggleAttributeColumn('existing.attr')
            }).toFinishAllListeners()

            expect(logic.values.configurableColumnsById['attribute-existing.attr']).toBeUndefined()
        })
    })

    describe('keyed instances', () => {
        it('maintains separate state for different keys', async () => {
            const logic1 = logsViewerColumnLogic({ id: 'tab-1' })
            const logic2 = logsViewerColumnLogic({ id: 'tab-2' })
            logic1.mount()
            logic2.mount()

            logic1.actions.addAttributeColumn('attr1')
            logic2.actions.addAttributeColumn('attr2')
            await expectLogic(logic1).toFinishAllListeners()
            await expectLogic(logic2).toFinishAllListeners()

            expect(logic1.values.configurableColumnsById['attribute-attr1']).toBeTruthy()
            expect(logic1.values.configurableColumnsById['attribute-attr2']).toBeUndefined()
            expect(logic2.values.configurableColumnsById['attribute-attr2']).toBeTruthy()
            expect(logic2.values.configurableColumnsById['attribute-attr1']).toBeUndefined()

            logic1.unmount()
            logic2.unmount()
        })
    })
})
