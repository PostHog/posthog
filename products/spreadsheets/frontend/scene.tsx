import 'handsontable/styles/handsontable.min.css'
import 'handsontable/styles/ht-theme-main.min.css'

import { HotTable } from '@handsontable/react-wrapper'
import Handsontable from 'handsontable'
// Import HyperFormula and its necessary types
import { FunctionArgumentType, FunctionPlugin, HyperFormula } from 'hyperformula'

// 1. Create a function plugin for SQL
class SqlPlugin extends FunctionPlugin {
    // @ts-expect-error - ast and state are provided by HyperFormula
    customSql(ast: any, state: any): any {
        return this.runFunction(
            ast.args,
            state,
            this.metadata('SQL'),
            // Implementation of the SQL function
            // For now, it ignores params and returns 100
            // Later, params[0] would be the SQL string
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            (..._params: any[]) => {
                return 100 // Dummy return value
            }
        )
    }

    // 2. Define the function's ID, method, and metadata as a static property
    public static implementedFunctions = {
        SQL: {
            method: 'customSql',
            parameters: [
                {
                    argumentType: FunctionArgumentType.STRING, // Expects the SQL query as a string
                    // Add more parameter definitions if needed, e.g., for optional arguments
                },
            ],
            // Add other options if necessary, e.g. isVolatile: true if it's a dynamic query
        },
    }
}

// 3. Add the function's names (translations)
const SqlPluginTranslations = {
    enGB: {
        SQL: 'SQL',
    },
    // Add other languages if needed, e.g., enUS: { SQL: 'SQL' }
}

// 4. Register the function plugin with HyperFormula
// This must be done BEFORE Handsontable initializes its HyperFormula instance.
// So, do it here at the top level of the module.
try {
    HyperFormula.registerFunctionPlugin(SqlPlugin, SqlPluginTranslations as any) // Cast as any to bypass strict lib checks if types mismatch
} catch (e) {
    // console.error('Error registering HyperFormula plugin:', e)
    // Fallback or error handling if registration fails
    // This might happen if HyperFormula is already initialized or if there's a version mismatch issue
    // For instance, if Handsontable has already created its own HF instance.
    // In such a case, we might need to get the HF instance from Handsontable and register on that.
}

export const SpreadsheetsScene = (): JSX.Element => {
    // Generate an empty 100 rows x 26 columns dataset
    const emptyData = Handsontable.helper.createEmptySpreadsheetData(50, 26)

    return (
        <div className="ht-theme-main-dark-auto">
            <HotTable
                data={emptyData} // Use the empty 100x26 dataset
                rowHeaders={true}
                colHeaders={true}
                minRows={50} // Ensure a minimum of 100 rows
                minCols={26} // Ensure a minimum of 26 columns (A-Z)
                minSpareRows={0} // No extra blank rows beyond the 100
                minSpareCols={0} // No extra blank columns beyond the 26
                height="auto" // Consider setting a fixed height e.g., 500 or '80vh' for large grids
                autoWrapRow={true}
                autoWrapCol={true}
                licenseKey="non-commercial-and-evaluation" // for non-commercial use only
                formulas={{
                    engine: HyperFormula,
                }}
                // Enable context menu for add/remove rows/columns and other operations
                contextMenu={true}
            />
        </div>
    )
}
