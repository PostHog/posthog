import { connect, kea, path, props, selectors } from 'kea'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventProperties, ErrorTrackingStackFrame, ExceptionAttributes } from 'lib/components/Errors/types'

import type { codeVariablesBannerLogicType } from './codeVariablesBannerLogicType'

export interface CodeVariablesBannerLogicProps {
    properties: ErrorEventProperties
    id: string
}

export const codeVariablesBannerLogic = kea<codeVariablesBannerLogicType>([
    path(['error-tracking', 'components', 'banners', 'codeVariablesBannerLogic']),

    props({} as CodeVariablesBannerLogicProps),

    connect((props: CodeVariablesBannerLogicProps) => ({
        values: [
            errorPropertiesLogic({ properties: props.properties, id: props.id }),
            ['exceptionAttributes', 'frames'],
        ],
    })),

    selectors({
        shouldShowBanner: [
            (s) => [s.exceptionAttributes, s.frames],
            (exceptionAttributes: ExceptionAttributes | null, frames: ErrorTrackingStackFrame[]) => {
                if (exceptionAttributes?.runtime !== 'python') {
                    return false
                }

                if (!frames || frames.length === 0) {
                    return false
                }

                return frames.every((frame: ErrorTrackingStackFrame) => !frame.code_variables)
            },
        ],
    }),
])
