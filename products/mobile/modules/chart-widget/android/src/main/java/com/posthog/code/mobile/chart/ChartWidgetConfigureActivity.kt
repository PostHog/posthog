package com.posthog.code.mobile.chart

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.AbsoluteSizeSpan
import android.text.style.ForegroundColorSpan
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.CheckBox
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.TextView

/** The launcher opens this when a Chart widget is placed or reconfigured. Plain views: React Native is not running. */
class ChartWidgetConfigureActivity : Activity() {
    private var widgetId = AppWidgetManager.INVALID_APPWIDGET_ID
    private var selected: String? = null
    private val extras = LinkedHashSet<String>()
    private val extraBoxes = mutableListOf<Pair<CatalogPin, CheckBox>>()
    private lateinit var content: LinearLayout
    private var footer: View? = null

    private fun isChartWidget(): Boolean = widgetId != AppWidgetManager.INVALID_APPWIDGET_ID &&
        AppWidgetManager.getInstance(this).getAppWidgetInfo(widgetId)?.provider ==
        ComponentName(this, ChartWidgetProvider::class.java)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Leaving any other way than Done must not place the widget.
        setResult(RESULT_CANCELED)
        widgetId = intent?.extras?.getInt(AppWidgetManager.EXTRA_APPWIDGET_ID, AppWidgetManager.INVALID_APPWIDGET_ID)
            ?: AppWidgetManager.INVALID_APPWIDGET_ID
        if (!isChartWidget()) {
            finish()
            return
        }
        content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(8), dp(20), dp(24))
        }
        content.addView(text("✕", 20f, R.color.chart_widget_ink).apply {
            contentDescription = getString(R.string.chart_widget_configure_close)
            layoutParams = LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT)
            setPadding(0, dp(8), dp(16), dp(8))
            setOnClickListener { finish() }
        })
        content.addView(text(getString(R.string.chart_widget_choose_pin), 26f, R.color.chart_widget_ink, bold = true))
        content.addView(text(getString(R.string.chart_widget_configure_subtitle), 14f, R.color.chart_widget_secondary).apply {
            setPadding(0, dp(6), 0, dp(12))
        })
        val catalog = ChartStore.catalog(this)
        when {
            catalog == null || catalog.pins.isEmpty() -> showMessage(getString(R.string.chart_widget_configure_empty))
            else -> showPicker(catalog)
        }
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            // The window draws behind the system bars, so the content keeps clear of them.
            fitsSystemWindows = true
            addView(ScrollView(this@ChartWidgetConfigureActivity).apply { addView(content, MATCH_PARENT, WRAP_CONTENT) },
                LinearLayout.LayoutParams(MATCH_PARENT, 0, 1f))
            // Done stays on screen however long the pin list is.
            footer?.let { addView(it) }
        })
    }

    private fun showMessage(message: String) {
        content.addView(text(message, 16f, R.color.chart_widget_ink).apply { setPadding(0, dp(24), 0, dp(16)) })
        content.addView(button(getString(R.string.chart_widget_configure_open_app)) {
            packageManager.getLaunchIntentForPackage(packageName)?.let(::startActivity)
            finish()
        })
    }

    private fun showPicker(catalog: Catalog) {
        val current = ChartStore.widgetConfig(this, widgetId)
        val eligible = catalog.pins.filter { it.eligible }
        val ineligible = catalog.pins.filter { !it.eligible }
        selected = current?.pinId?.takeIf { id -> eligible.any { it.id == id } } ?: eligible.firstOrNull()?.id
        current?.extraPinIds?.filter { id -> eligible.any { it.id == id } }?.let(extras::addAll)
        lateinit var done: Button

        val group = RadioGroup(this)
        eligible.forEach { pin ->
            group.addView(RadioButton(this).apply {
                id = View.generateViewId()
                text = twoLines(pin.name, pin.subtitle)
                buttonTintList = ColorStateList.valueOf(color(R.color.chart_widget_ink))
                setPadding(dp(8), dp(10), 0, dp(10))
                isChecked = pin.id == selected
                setOnCheckedChangeListener { _, checked ->
                    if (!checked) return@setOnCheckedChangeListener
                    selected = pin.id
                    extras.remove(pin.id)
                    updateExtras()
                    done.isEnabled = true
                    done.alpha = 1f
                }
            })
        }
        content.addView(group)

        if (ineligible.isNotEmpty()) {
            content.addView(header(getString(R.string.chart_widget_configure_ineligible)))
            ineligible.forEach { pin ->
                content.addView(text("", 16f, R.color.chart_widget_ink).apply {
                    text = twoLines(pin.name, pin.reason ?: getString(R.string.chart_widget_ineligible))
                    alpha = 0.45f
                    setPadding(dp(40), dp(10), 0, dp(10))
                })
            }
        }

        if (eligible.size > 1) {
            content.addView(header(getString(R.string.chart_widget_configure_extras)))
            eligible.forEach { pin ->
                val box = CheckBox(this).apply {
                    text = pin.name
                    textSize = 16f
                    setTextColor(color(R.color.chart_widget_ink))
                    buttonTintList = ColorStateList.valueOf(color(R.color.chart_widget_ink))
                    setPadding(dp(8), dp(8), 0, dp(8))
                    isChecked = pin.id in extras
                    setOnCheckedChangeListener { _, checked ->
                        if (checked) extras.add(pin.id) else extras.remove(pin.id)
                        updateExtras()
                    }
                }
                extraBoxes.add(pin to box)
                content.addView(box)
            }
            updateExtras()
        }

        done = button(getString(R.string.chart_widget_configure_done)) { save(catalog) }
        done.isEnabled = selected != null
        done.alpha = if (selected != null) 1f else 0.4f
        (done.layoutParams as LinearLayout.LayoutParams).topMargin = 0
        footer = LinearLayout(this).apply {
            setPadding(dp(20), dp(12), dp(20), dp(12))
            addView(done)
        }
    }

    /** The primary pin is not offered twice, and at most two extras fit the large widget. */
    private fun updateExtras() {
        extraBoxes.forEach { (pin, box) ->
            val primary = pin.id == selected
            if (primary && box.isChecked) box.isChecked = false
            box.isEnabled = !primary && (box.isChecked || extras.size < 2)
            box.alpha = if (box.isEnabled) 1f else 0.45f
        }
    }

    private fun save(catalog: Catalog) {
        if (!isChartWidget()) {
            finish()
            return
        }
        val pin = catalog.pin(selected ?: return) ?: return
        ChartStore.setWidgetConfig(
            this, widgetId, pin.id, extras.filter { it != pin.id }.take(2),
            projectId = catalog.projectId, projectName = catalog.projectName, pinName = pin.name,
        )
        ChartWidgetRefresh.refreshAll(this)
        setResult(RESULT_OK, Intent().putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, widgetId))
        finish()
        if (ChartStore.credentials(this) == null) {
            packageManager.getLaunchIntentForPackage(packageName)?.let(::startActivity)
        }
    }

    private fun twoLines(title: String, subtitle: String): CharSequence {
        val text = SpannableStringBuilder(title)
        if (subtitle.isNotBlank()) {
            val start = text.length
            text.append("\n").append(subtitle)
            text.setSpan(AbsoluteSizeSpan(13, true), start, text.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            text.setSpan(ForegroundColorSpan(color(R.color.chart_widget_secondary)), start, text.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        return text
    }

    private fun header(label: String): TextView = text(label, 12f, R.color.chart_widget_tertiary, bold = true).apply {
        isAllCaps = true
        letterSpacing = 0.08f
        setPadding(0, dp(20), 0, dp(6))
    }

    private fun text(value: String, size: Float, colorRes: Int, bold: Boolean = false): TextView = TextView(this).apply {
        text = value
        textSize = size
        setTextColor(color(colorRes))
        if (bold) typeface = Typeface.create("sans-serif-medium", Typeface.BOLD)
    }

    private fun button(label: String, onClick: () -> Unit): Button = Button(this).apply {
        text = label
        isAllCaps = false
        textSize = 16f
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        setTextColor(color(R.color.chart_widget_on_orange))
        background = GradientDrawable().apply {
            setColor(color(R.color.chart_widget_orange))
            cornerRadius = dp(24).toFloat()
        }
        stateListAnimator = null
        gravity = Gravity.CENTER
        layoutParams = LinearLayout.LayoutParams(MATCH_PARENT, dp(48)).apply { topMargin = dp(24) }
        setOnClickListener { onClick() }
    }

    private fun color(res: Int): Int = getColor(res)

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
