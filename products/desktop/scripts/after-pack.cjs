/**
 * electron-builder afterPack hook: ad-hoc codesign the packed .app.
 *
 * We have no signing identity yet, but Apple Silicon refuses to launch code
 * with no signature at all, so an ad-hoc signature (identity "-") is the
 * minimum for the DMG to be usable. Users still have to clear the quarantine
 * flag (right-click > Open, or xattr -d com.apple.quarantine) until we sign
 * and notarize for real.
 */

const { execFileSync } = require('node:child_process')
const path = require('node:path')

exports.default = async function afterPack(context) {
    if (context.electronPlatformName !== 'darwin') {
        return
    }
    const appPath = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`)
    execFileSync('codesign', ['--force', '--deep', '--sign', '-', appPath], { stdio: 'inherit' })
}
