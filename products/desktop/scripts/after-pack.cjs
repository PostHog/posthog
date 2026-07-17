/**
 * electron-builder afterPack hook: ad-hoc codesign the packed .app when no
 * real signing identity is available.
 *
 * Apple Silicon refuses to launch code with no signature at all, so an ad-hoc
 * signature (identity "-") is the minimum for an unsigned DMG to be usable.
 * Users of such builds still have to clear the quarantine flag (right-click >
 * Open, or xattr -d com.apple.quarantine). When CSC_LINK is set,
 * electron-builder signs with the real Developer ID cert right after this
 * hook, so the ad-hoc pass is skipped.
 */

const { execFileSync } = require('node:child_process')
const path = require('node:path')

exports.default = async function afterPack(context) {
    if (context.electronPlatformName !== 'darwin') {
        return
    }
    if (process.env.CSC_LINK) {
        return
    }
    const appPath = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`)
    execFileSync('codesign', ['--force', '--deep', '--sign', '-', appPath], { stdio: 'inherit' })
}
