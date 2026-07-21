import * as fs from 'fs'

import { expect, test } from '@playwright-utils/workspace-test-base'

test('product scope matrix probe', () => {
    if (process.env.QMATRIX_MARKER_PRODUCT) {
        fs.appendFileSync(process.env.QMATRIX_MARKER_PRODUCT, 'executed\n')
    }
    expect(1).toBe(2)
})
