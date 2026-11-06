const { AndroidConfig, withAndroidManifest } = require('expo/config-plugins')

module.exports = function withAndroidChartWidgetBackup(config) {
    return withAndroidManifest(config, (cfg) => {
        const application = AndroidConfig.Manifest.getMainApplicationOrThrow(cfg.modResults)
        application.$['android:fullBackupContent'] = '@xml/chart_widget_backup_rules'
        application.$['android:dataExtractionRules'] = '@xml/chart_widget_data_extraction_rules'
        return cfg
    })
}
