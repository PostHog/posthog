import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from '~/lib/api'

import { llmSkillsNameFilesRetrieve } from 'products/skills/frontend/generated/api'
import type { LLMSkillFileApi } from 'products/skills/frontend/generated/api.schemas'

import type { skillFileLogicType } from './skillFileLogicType'

export interface SkillFileLogicProps {
    skillName: string
    filePath: string
    version?: number
}

export const skillFileLogic = kea<skillFileLogicType>([
    path(['scenes', 'skills', 'skillFileLogic']),
    props({ skillName: '', filePath: '' } as SkillFileLogicProps),
    key(({ skillName, filePath, version }) => `skill-file-${skillName}:${filePath}:${version ?? 'latest'}`),
    actions({
        toggleExpand: true,
        autoOpen: true,
    }),
    reducers({
        expanded: [
            false,
            {
                toggleExpand: (state) => !state,
                autoOpen: () => true,
            },
        ],
    }),
    loaders(({ props }) => ({
        content: {
            __default: null as string | null,
            loadContent: async () => {
                try {
                    const fileData: LLMSkillFileApi = await llmSkillsNameFilesRetrieve(
                        String(ApiConfig.getCurrentTeamId()),
                        props.skillName,
                        props.filePath,
                        { version: props.version }
                    )
                    return fileData.content
                } catch (e) {
                    console.error('Failed to load file content', e)
                    return 'Failed to load file content.'
                }
            },
        },
    })),
    listeners(({ actions, values }) => ({
        toggleExpand: () => {
            if (values.expanded && values.content === null && !values.contentLoading) {
                actions.loadContent()
            }
        },
        autoOpen: () => {
            if (values.content === null && !values.contentLoading) {
                actions.loadContent()
            }
        },
    })),
])
