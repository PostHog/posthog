import { spawnSync } from 'node:child_process'

/**
 * Format JS/TS files using `hogli format:js`.
 *
 * @param {string[]} files - absolute paths to format
 * @param {string} hogliPath - absolute path to the hogli binary
 * @param {string} cwd - working directory for the hogli call
 */
export function formatJs(files, hogliPath, cwd) {
    if (files.length === 0) {
        return
    }
    spawnSync(hogliPath, ['format:js', ...files], { stdio: 'pipe', cwd })
}

/**
 * Format JSON/YAML files using `hogli format:yaml` (runs oxfmt).
 *
 * @param {string[]} files - absolute paths to format
 * @param {string} hogliPath - absolute path to the hogli binary
 * @param {string} cwd - working directory for the hogli call
 */
export function formatYaml(files, hogliPath, cwd) {
    if (files.length === 0) {
        return
    }
    spawnSync(hogliPath, ['format:yaml', ...files], { stdio: 'pipe', cwd })
}
