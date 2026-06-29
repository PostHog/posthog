import { build } from 'esbuild'

import { agentProxyEsbuildOptions, agentProxyOutfile } from './agent-proxy-esbuild-config'

build(agentProxyEsbuildOptions())
    .then(() => {
        console.info(`Built agent-proxy server → ${agentProxyOutfile}`)
    })
    .catch((err: unknown) => {
        console.error('Build failed:', err)
        process.exit(1)
    })
