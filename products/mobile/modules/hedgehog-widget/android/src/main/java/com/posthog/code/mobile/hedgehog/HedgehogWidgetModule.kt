package com.posthog.code.mobile.hedgehog

import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import kotlin.concurrent.thread

class HedgehogWidgetModule : Module() {
    override fun definition() = ModuleDefinition {
        Name("HedgehogWidget")

        Function("setChoreography") { json: String ->
            store(json)
        }

        Function("clearChoreography") {
            store(null)
        }
    }

    private fun store(json: String?) {
        val context = appContext.reactContext?.applicationContext ?: throw Exceptions.ReactContextLost()
        HedgehogStore.setChoreographyJson(context, json)
        // A full day of loops is a large JSON document, so parse and render off the JS thread.
        thread(name = "HedgehogWidgetRender") { HedgehogRenderer.renderAll(context) }
    }
}
