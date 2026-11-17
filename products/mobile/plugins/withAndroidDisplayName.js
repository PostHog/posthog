const { AndroidConfig, withStringsXml } = require('expo/config-plugins')

module.exports = function withAndroidDisplayName(config, { name }) {
    return withStringsXml(config, (cfg) => {
        cfg.modResults = AndroidConfig.Strings.setStringItem(
            [AndroidConfig.Resources.buildResourceItem({ name: 'app_name', value: name })],
            cfg.modResults
        )
        return cfg
    })
}
