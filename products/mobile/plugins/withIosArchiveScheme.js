const { existsSync, renameSync } = require('node:fs')
const { basename, join } = require('node:path')

const { IOSConfig, withDangerousMod } = require('expo/config-plugins')

const eas = require('../eas.json')

module.exports = function withIosArchiveScheme(config) {
    return withDangerousMod(config, [
        'ios',
        (cfg) => {
            const project = IOSConfig.Paths.getXcodeProjectPath(cfg.modRequest.projectRoot)
            const schemes = join(project, 'xcshareddata', 'xcschemes')
            const original = join(schemes, `${basename(project, '.xcodeproj')}.xcscheme`)
            const archive = join(schemes, `${eas.build.base.ios.scheme}.xcscheme`)

            if (existsSync(original) || !existsSync(archive)) {
                renameSync(original, archive)
            }
            return cfg
        },
    ])
}
