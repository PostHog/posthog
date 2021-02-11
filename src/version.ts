import { readFileSync } from 'fs'
import * as path from 'path'

export const { version } = JSON.parse(readFileSync(path.resolve(__dirname, '../package.json')).toString())
