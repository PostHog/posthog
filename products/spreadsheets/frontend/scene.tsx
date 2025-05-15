import 'handsontable/styles/handsontable.min.css'
import 'handsontable/styles/ht-theme-main.min.css'

import { HotTable, HotTableRef } from '@handsontable/react-wrapper'
import Handsontable from 'handsontable'
import { CellChange, ChangeSource } from 'handsontable/common'
import { BaseRenderer } from 'handsontable/renderers'
import { CellMeta } from 'handsontable/settings'
import {
    CellValue,
    DetailedCellError,
    ErrorType,
    FunctionArgumentType,
    FunctionPlugin,
    HyperFormula,
} from 'hyperformula'
import { useActions, useValues } from 'kea'
import api from 'lib/api'
import { useEffect, useMemo, useRef } from 'react'

import { FormulaBar } from './components/FormulaBar'
import { DEFAULT_COLUMN_WIDTH, DEFAULT_COLUMNS_COUNT, spreadsheetsSceneLogic } from './spreadsheetsSceneLogic'

// Interface for SqlPlugin remains useful for this.hot, this.hf if needed by other methods,
// but sheetId, row, col might not be needed in customSql if args are pre-evaluated.
// eslint-disable-next-line @typescript-eslint/no-unsafe-declaration-merging
interface SqlPlugin extends FunctionPlugin {
    // Removed hot, hf from instance if not used elsewhere, focus on static for rendering
    // hot?: Handsontable.Core // Instance-specific hot, might not be reliable for async
    // hf?: HyperFormula      // Instance-specific hf
    sheetId?: number
    row?: number
    col?: number
    dependencies?: {
        computedValue: (ast: any, sheetId: number, row: number, col: number) => CellValue | DetailedCellError
    }
}

// eslint-disable-next-line @typescript-eslint/no-unsafe-declaration-merging
class SqlPlugin extends FunctionPlugin {
    // Static property to hold the Handsontable instance
    public static hotInstance?: Handsontable.Core

    // Cache and fetches in progress are now static to be shared across all invocations/instances
    private static queryCache: Map<
        string,
        { status: 'loading' | 'success' | 'error'; data?: CellValue; error?: string }
    > = new Map()
    private static fetchesInProgress: Set<string> = new Set()

    // astNode here is the {type: 'FUNCTION_CALL', ...} object for our =SQL() function itself.
    // The actual argument (the SQL string AST) is in astNode.args[0].
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    customSql(astNode: any, _sheetValues: CellValue[][]): CellValue | string {
        const MyClass = this.constructor as typeof SqlPlugin
        let sqlQueryString: string | undefined

        // Attempt to directly extract from AST if it's a simple string literal node
        if (astNode && astNode.args && astNode.args[0]) {
            const firstArgAst = astNode.args[0]
            if (firstArgAst.type === 'STRING') {
                // Common AST type for string literals
                sqlQueryString = firstArgAst.value
            } else {
                try {
                    if (
                        !this.dependencies ||
                        this.sheetId === undefined ||
                        this.row === undefined ||
                        this.col === undefined
                    ) {
                        return '#ERROR! Context Missing'
                    }
                    const evaluatedArgResult = this.dependencies.computedValue(
                        firstArgAst,
                        this.sheetId,
                        this.row,
                        this.col
                    )
                    if (evaluatedArgResult instanceof DetailedCellError) {
                        const errorTypeStr = ErrorType[evaluatedArgResult.type]
                        return errorTypeStr ? `#${errorTypeStr}!` : '#ERROR!'
                    }
                    sqlQueryString = String(evaluatedArgResult)
                } catch (e: any) {
                    return '#ERROR! Arg Eval'
                }
            }
        } else {
            return '#VALUE! Missing SQL query'
        }

        if (typeof sqlQueryString !== 'string' || !sqlQueryString.trim()) {
            return '#VALUE! Invalid SQL'
        }

        // 1. Check static cache for final result or explicit loading state
        if (MyClass.queryCache.has(sqlQueryString)) {
            const cachedEntry = MyClass.queryCache.get(sqlQueryString)!
            if (cachedEntry.status === 'success') {
                return cachedEntry.data!
            }
            if (cachedEntry.status === 'error') {
                return cachedEntry.error!
            }
            if (cachedEntry.status === 'loading') {
                return 'LOADING...'
            } // Already loading
        }

        // 2. Check if a fetch is already in progress (if not found in cache or cache was stale)
        if (MyClass.fetchesInProgress.has(sqlQueryString)) {
            // Ensure cache is marked as loading if somehow it wasn't (should be redundant if logic is tight)
            if (
                !MyClass.queryCache.has(sqlQueryString) ||
                MyClass.queryCache.get(sqlQueryString)?.status !== 'loading'
            ) {
                MyClass.queryCache.set(sqlQueryString, { status: 'loading' })
            }
            return 'LOADING...'
        }

        // 3. If not cached definitively and not in progress, initiate fetch
        MyClass.fetchesInProgress.add(sqlQueryString)
        MyClass.queryCache.set(sqlQueryString, { status: 'loading' }) // Mark as loading BEFORE the async call

        api.query({ kind: 'HogQLQuery', query: sqlQueryString })
            .then((response: any) => {
                let resultToCache: { status: 'success'; data: CellValue } | { status: 'error'; error: string }
                if (
                    response &&
                    response.results &&
                    Array.isArray(response.results) &&
                    response.results.length > 0 &&
                    Array.isArray(response.results[0]) &&
                    response.results[0].length > 0
                ) {
                    const cellData = response.results[0][0]
                    if (
                        typeof cellData === 'string' ||
                        typeof cellData === 'number' ||
                        typeof cellData === 'boolean' ||
                        cellData === null
                    ) {
                        resultToCache = { status: 'success', data: cellData as CellValue }
                    } else {
                        resultToCache = { status: 'error', error: '#VALUE! Unsupported data' }
                    }
                } else if (
                    response &&
                    response.results &&
                    (response.results.length === 0 ||
                        (Array.isArray(response.results[0]) && response.results[0].length === 0))
                ) {
                    resultToCache = { status: 'success', data: null } // Empty result is a valid success (null data)
                } else {
                    resultToCache = { status: 'error', error: '#N/A Response error' }
                }
                MyClass.queryCache.set(sqlQueryString, resultToCache)
            })
            .catch((error) => {
                let errorMessage = '#ERROR! API Failed'
                if (error.detail) {
                    errorMessage = `#ERROR! ${error.detail}`
                } else if (error.message) {
                    errorMessage = `#ERROR! ${error.message}`
                }
                MyClass.queryCache.set(sqlQueryString, {
                    status: 'error',
                    error: errorMessage.substring(0, 255),
                })
            })
            .finally(() => {
                const MyClass = this.constructor as typeof SqlPlugin
                MyClass.fetchesInProgress.delete(sqlQueryString)

                if (MyClass.hotInstance) {
                    const formulasPlugin = MyClass.hotInstance.getPlugin('formulas') as any
                    const hfEngine = formulasPlugin?.engine as HyperFormula
                    // let recalculated = false // Unused variable

                    if (hfEngine && typeof hfEngine.rebuildAndRecalculate === 'function') {
                        try {
                            hfEngine.rebuildAndRecalculate()
                            // recalculated = true // Unused assignment
                        } catch (e: any) {
                            // Intentional: Best effort, render will happen regardless
                        }
                    }
                    try {
                        MyClass.hotInstance.render()
                    } catch (e: any) {
                        // Intentional: Render might fail if instance is gone, but we tried
                    }
                }
            })

        return 'LOADING...' // This is returned while the fetch is happening
    }

    // Static metadata for the SQL function
    public static implementedFunctions = {
        SQL: {
            method: 'customSql',
            parameters: [
                {
                    // This describes the *expected* type of the argument for HyperFormula to aim for,
                    // but our plugin method will still receive an AST for it if it's complex.
                    // Or rather, the `astNode` param of `customSql` is the SQL function call, `astNode.args[0]` is its first param AST.
                    argumentType: FunctionArgumentType.ANY, // Change to ANY as we are handling the evaluation
                },
            ],
            // API calls are inherently volatile, their results can change without sheet inputs changing
            isVolatile: true,
        },
    }
}

// 3. Add the function's names (translations)
const SqlPluginTranslations = {
    enGB: {
        SQL: 'SQL',
    },
}

// 4. Register the function plugin with HyperFormula
// This must be done BEFORE Handsontable initializes its HyperFormula instance.
// So, do it here at the top level of the module.
try {
    HyperFormula.registerFunctionPlugin(SqlPlugin, SqlPluginTranslations as any) // Cast as any to bypass strict lib checks if types mismatch
} catch (e) {
    // Fallback or error handling if registration fails
    // This might happen if HyperFormula is already initialized or if there's a version mismatch issue
    // For instance, if Handsontable has already created its own HF instance.
    // In such a case, we might need to get the HF instance from Handsontable and register on that.
}

export const SpreadsheetsScene = (): JSX.Element => {
    // Generate an empty 100 rows x (26 * 2) columns dataset
    const hotRef = useRef<HotTableRef>(null)
    const formulaContainerRef = useRef<HTMLDivElement>(null)
    const { data, settings, formatting } = useValues(spreadsheetsSceneLogic)
    const {
        setCurrentCellValue,
        setCurrentCellMeta,
        setData,
        setHotRef,
        saveDataToServer,
        updateColumnWidth,
        toggleBoldCell,
    } = useActions(spreadsheetsSceneLogic)

    useEffect(() => {
        const currentHotRef = hotRef.current
        if (currentHotRef) {
            setHotRef(currentHotRef) // Call Kea action
            const hotInstance = currentHotRef.hotInstance
            if (hotInstance) {
                // Make the Handsontable instance statically available to the plugin
                SqlPlugin.hotInstance = hotInstance

                // The global HyperFormula.registerFunctionPlugin at the module level should be sufficient.
                // If issues persist with plugin recognition, further investigation into HOT's HF initialization timing
                // relative to global registration would be needed. For now, we assume global registration works.
            }
        }
    }, [hotRef, setHotRef]) // Effect runs when hotRef.current is populated.

    useEffect(() => {
        const hot = hotRef.current?.hotInstance
        if (!hot) {
            return
        }

        const shortcutManager = hot.getShortcutManager()
        const gridContext = shortcutManager.getContext('grid')

        if (!gridContext) {
            return
        }

        gridContext.addShortcut({
            keys: [
                ['Control', 'B'],
                ['Meta', 'B'],
            ],
            callback: () => {
                const selected = hot.getSelected()

                if (!selected) {
                    return
                }

                selected.forEach(([rowStart, colStart, rowEnd, colEnd]) => {
                    for (let row = rowStart; row <= rowEnd; row++) {
                        for (let col = colStart; col <= colEnd; col++) {
                            toggleBoldCell(row, col)
                        }
                    }
                })

                hot.render()
            },
            group: 'customBoldFormatting',
        })
    }, [hotRef.current])

    const handleAfterChange = (changes: CellChange[] | null, source: ChangeSource): void => {
        if ((source === 'edit' || source === 'updateData') && changes) {
            const newData = [...data]

            changes.forEach(([row, col, oldValue, newValue]) => {
                if (oldValue !== newValue) {
                    newData[row][col as number] = newValue
                }
            })

            setData(newData)
            saveDataToServer({ data: newData })
        }
    }

    const cellRenderer: BaseRenderer = (instance, td, row, column, ...rest) => {
        Handsontable.renderers.TextRenderer(instance, td, row, column, ...rest)

        if (!formatting) {
            return
        }

        const bold = formatting[row]?.[column]?.bold
        if (bold === true) {
            td.style.fontWeight = 'bold'
        }
        // td.style.color = 'green'
        // td.style.background = '#CEC'
    }

    const spreadsheetHeight = useMemo(() => {
        if (formulaContainerRef?.current) {
            return `calc(100vh - ${formulaContainerRef.current.offsetHeight}px)`
        }

        return '100vh'
    }, [formulaContainerRef?.current])

    return (
        <>
            <FormulaBar ref={formulaContainerRef} />
            <div className="ht-theme-main-dark-auto">
                <HotTable
                    afterChange={handleAfterChange}
                    ref={hotRef}
                    afterSelection={(rowIndex, columnIndex) => {
                        setCurrentCellValue(data[rowIndex][columnIndex])
                        const cellMeta = hotRef.current?.hotInstance?.getCellMeta(rowIndex, columnIndex)
                        setCurrentCellMeta(cellMeta ?? null)
                    }}
                    cells={() => {
                        const cellProperties: CellMeta = {}
                        cellProperties.renderer = cellRenderer
                        return cellProperties
                    }}
                    data={data} // Use the empty 100x26 dataset
                    rowHeaders={true}
                    colHeaders={true}
                    manualColumnResize={true}
                    colWidths={(
                        settings.columnWidths ?? Array(settings.columnCount ?? DEFAULT_COLUMNS_COUNT).fill(null)
                    ).map((n) => n ?? DEFAULT_COLUMN_WIDTH)}
                    minRows={50} // Ensure a minimum of 100 rows
                    minCols={26} // Ensure a minimum of 26 columns (A-Z)
                    minSpareRows={0} // No extra blank rows beyond the 100
                    minSpareCols={0} // No extra blank columns beyond the 26
                    height={spreadsheetHeight}
                    autoWrapRow={false}
                    wordWrap={false}
                    autoWrapCol={false}
                    afterColumnResize={(size, columnIndex) => {
                        updateColumnWidth(size, columnIndex)
                    }}
                    licenseKey="non-commercial-and-evaluation" // for non-commercial use only
                    formulas={{
                        engine: HyperFormula,
                    }}
                    // Enable context menu for add/remove rows/columns and other operations
                    contextMenu={true}
                />
            </div>
        </>
    )
}
