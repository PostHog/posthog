import { connect, kea, path, selectors } from 'kea'

import { ErrorPropertiesLogicProps, errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorTrackingStackFrame, ExceptionAttributes } from 'lib/components/Errors/types'

import type { codeVariablesBannerLogicType } from './codeVariablesBannerLogicType'

export const codeVariablesBannerLogic = kea<codeVariablesBannerLogicType>([
    path(['error-tracking', 'components', 'banners', 'codeVariablesBannerLogic']),

    connect((props: ErrorPropertiesLogicProps) => ({
        values: [errorPropertiesLogic(props), ['exceptionAttributes', 'frames']],
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
