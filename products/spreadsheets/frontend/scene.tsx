import '@fortune-sheet/react/dist/index.css'

import { Workbook } from '@fortune-sheet/react'

export const SpreadsheetsScene = (): JSX.Element => {
    const data = [
        {
            name: 'Sheet1',
            row: 100,
            column: 26,
        },
    ]

    return (
        <div className="h-100 w-full">
            <Workbook data={data} />
        </div>
    )
}
