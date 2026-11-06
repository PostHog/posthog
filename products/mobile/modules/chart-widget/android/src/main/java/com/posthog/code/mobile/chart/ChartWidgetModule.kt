package com.posthog.code.mobile.chart

import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class ChartWidgetModule : Module() {
    override fun definition() = ModuleDefinition {
        Name("ChartWidget")

        Function("setCredentials") { json: String ->
            ChartStore.setCredentials(context(), json)
            ChartWidgetRefresh.refreshAll(context())
        }

        Function("clearCredentials") {
            ChartStore.clearCredentials(context())
            ChartWidgetRefresh.refreshAll(context())
        }

        Function("setCatalog") { json: String ->
            ChartStore.setCatalogJson(context(), json)
            ChartWidgetRefresh.refreshAll(context())
        }

        Function("clearCatalog") {
            ChartStore.setCatalogJson(context(), null)
            ChartWidgetRefresh.refreshAll(context())
        }

        Function("reloadWidgets") {
            ChartWidgetRefresh.refreshAll(context())
        }
    }

    private fun context() = appContext.reactContext?.applicationContext ?: throw Exceptions.ReactContextLost()
}
