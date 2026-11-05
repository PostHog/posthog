import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const result = spawnSync(process.execPath, [require.resolve('expo/bin/cli'), 'install', '--check'], {
    // Bundled SDK versions keep CI independent of newer remote patch metadata.
    env: { ...process.env, EXPO_OFFLINE: '1' },
    stdio: 'inherit',
})

if (result.error) {
    throw result.error
}
if (result.signal) {
    process.kill(process.pid, result.signal)
} else {
    process.exitCode = result.status ?? 1
}
