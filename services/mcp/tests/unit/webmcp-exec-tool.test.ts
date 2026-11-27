import { describe, expect, it } from 'vitest'

import { WEBMCP_EXEC_TOOL } from '../../../../products/webmcp/frontend/execTool.generated'
import { renderWebMcpExecTool } from '../../scripts/lib/render-webmcp-exec-tool'

describe('WebMCP exec tool', () => {
    it('matches the committed definition, else run hogli build:openapi-webmcp-exec-tool', () => {
        expect(WEBMCP_EXEC_TOOL).toEqual(renderWebMcpExecTool())
    })
})
