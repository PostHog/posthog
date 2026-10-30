const { join } = require('node:path')

const { withFinalizedMod, XML } = require('expo/config-plugins')

// Adaptive layers are 108dp, but launchers mask them to the central 72dp.
// Scale the artwork into that viewport so the hedgehog fits the 66dp safe circle.
const INSET = `${(18 / 108) * 100}%`

module.exports = function withAndroidAdaptiveIconInsets(config) {
    return withFinalizedMod(config, [
        'android',
        async (cfg) => {
            const resourceDir = join(cfg.modRequest.platformProjectRoot, 'app/src/main/res/mipmap-anydpi-v26')
            for (const name of ['ic_launcher.xml', 'ic_launcher_round.xml']) {
                const path = join(resourceDir, name)
                const xml = await XML.readXMLAsync({ path })
                xml['adaptive-icon'].foreground = [
                    {
                        inset: [
                            {
                                $: {
                                    'android:inset': INSET,
                                    'android:drawable': '@mipmap/ic_launcher_foreground',
                                },
                            },
                        ],
                    },
                ]
                await XML.writeXMLAsync({ path, xml })
            }
            return cfg
        },
    ])
}
