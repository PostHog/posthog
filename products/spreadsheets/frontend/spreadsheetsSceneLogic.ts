import { kea, path } from 'kea'

import type { spreadsheetsSceneLogicType } from './spreadsheetsSceneLogicType'

export const spreadsheetsSceneLogic = kea<spreadsheetsSceneLogicType>([
    path(['products', 'spreadsheets', 'frontend', 'spreadsheetsSceneLogic']),
])
