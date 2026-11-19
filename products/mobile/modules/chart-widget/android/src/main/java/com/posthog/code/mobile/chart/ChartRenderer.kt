package com.posthog.code.mobile.chart

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.util.Log
import android.util.TypedValue
import android.view.View
import android.widget.RemoteViews
import java.util.concurrent.Executors
import java.util.concurrent.Future
import kotlin.math.max

object ChartRenderer {
    private val renderExecutor = Executors.newSingleThreadExecutor()

    const val TAG = "ChartWidget"

    private const val DEFAULT_SIZE_DP = 180
    private const val STALE_MS = 60 * 60_000L
    private const val SHORT_POINTS = 14
    private const val MIN_CHART_DP = 16f

    enum class Family(val key: String) { SMALL("small"), MEDIUM("medium"), LARGE("large") }

    private class Inputs(val credentials: Credentials?, val catalog: Catalog?, val now: Long)

    private sealed class Resolved {
        class Message(
            val title: String?,
            val message: String,
            val detail: String? = null,
            val placeholder: Boolean = false,
            val linkPin: CatalogPin? = null,
        ) : Resolved()

        class Data(val pin: CatalogPin, val snapshot: ChartSnapshot, val extras: List<Extra>) : Resolved()
    }

    private class Extra(val pin: CatalogPin, val snapshot: ChartSnapshot?, val error: SnapshotError?)

    private fun failureText(context: Context, kind: String): Pair<String, String?> = when (kind) {
        ErrorKind.AUTH -> context.getString(R.string.chart_widget_update_session) to null
        ErrorKind.NOT_FOUND -> context.getString(R.string.chart_widget_not_found_short) to null
        ErrorKind.BAD_DATA -> context.getString(R.string.chart_widget_bad_data) to null
        ErrorKind.NO_RESULT -> context.getString(R.string.chart_widget_no_result) to null
        else -> context.getString(R.string.chart_widget_refresh_failed) to context.getString(R.string.chart_widget_refresh_retry)
    }

    private class TileIds(
        val root: Int, val title: Int, val range: Int, val value: Int, val delta: Int, val frame: Int, val light: Int, val dark: Int,
    )

    private val TILES = listOf(
        TileIds(R.id.chart_tile_1, R.id.chart_tile_1_title, R.id.chart_tile_1_range, R.id.chart_tile_1_value, R.id.chart_tile_1_delta,
            R.id.chart_tile_1_frame, R.id.chart_tile_1_image_light, R.id.chart_tile_1_image_dark),
        TileIds(R.id.chart_tile_2, R.id.chart_tile_2_title, R.id.chart_tile_2_range, R.id.chart_tile_2_value, R.id.chart_tile_2_delta,
            R.id.chart_tile_2_frame, R.id.chart_tile_2_image_light, R.id.chart_tile_2_image_dark),
    )

    fun widgetIds(context: Context): IntArray =
        AppWidgetManager.getInstance(context).getAppWidgetIds(ComponentName(context, ChartWidgetProvider::class.java))

    /** Catches everything, because an exception thrown from a broadcast receiver crashes the whole app process. */
    fun renderAll(context: Context): Future<*> {
        val app = context.applicationContext
        return renderExecutor.submit { renderAllNow(app) }
    }

    private fun renderAllNow(context: Context) {
        try {
            val ids = widgetIds(context)
            if (ids.isEmpty()) return
            val manager = AppWidgetManager.getInstance(context)
            val inputs = inputs(context)
            ids.forEach { render(context, manager, it, inputs) }
        } catch (e: Exception) {
            Log.e(TAG, "Could not render the chart widgets", e)
        }
    }

    fun renderOne(context: Context, manager: AppWidgetManager, id: Int, onComplete: () -> Unit = {}): Future<*> {
        val app = context.applicationContext
        return renderExecutor.submit {
            try {
                render(app, manager, id, inputs(app))
            } catch (e: Exception) {
                Log.e(TAG, "Could not render chart widget $id", e)
            } finally {
                onComplete()
            }
        }
    }

    private fun inputs(context: Context) =
        Inputs(ChartStore.credentials(context), ChartStore.catalog(context), System.currentTimeMillis())

    private fun render(context: Context, manager: AppWidgetManager, id: Int, inputs: Inputs) {
        try {
            manager.updateAppWidget(id, build(context, manager, id, inputs))
        } catch (e: Exception) {
            Log.e(TAG, "Could not render chart widget $id", e)
        }
    }

    private fun build(context: Context, manager: AppWidgetManager, id: Int, inputs: Inputs): RemoteViews {
        val options = manager.getAppWidgetOptions(id)
        // Portrait size: the launcher reports min width and max height for the portrait cell grid.
        val widthDp = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_WIDTH).takeIf { it > 0 } ?: DEFAULT_SIZE_DP
        val heightDp = options.getInt(AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT).takeIf { it > 0 } ?: DEFAULT_SIZE_DP
        val family = when {
            widthDp < 250 || heightDp < 110 -> Family.SMALL
            heightDp >= 300 -> Family.LARGE
            else -> Family.MEDIUM
        }
        return when (val resolved = resolve(context, ChartStore.widgetConfig(context, id), inputs)) {
            is Resolved.Message -> stateViews(context, id, family, resolved)
            is Resolved.Data -> dataViews(context, id, family, widthDp, heightDp, resolved, inputs.now)
        }
    }

    private fun resolve(context: Context, config: WidgetConfig?, inputs: Inputs): Resolved {
        if (config == null) {
            return Resolved.Message(context.getString(R.string.chart_widget_choose_pin), context.getString(R.string.chart_widget_choose_pin_hint))
        }
        val credentials = inputs.credentials ?: return Resolved.Message(
            context.getString(R.string.chart_widget_signed_out_title),
            context.getString(R.string.chart_widget_signed_out_message),
        )
        if (config.projectId != null && config.projectId != credentials.projectId) {
            val project = config.projectName?.takeIf { it.isNotBlank() } ?: "its project"
            return Resolved.Message(
                context.getString(R.string.chart_widget_other_project_title),
                context.getString(R.string.chart_widget_other_project_message, project),
            )
        }
        val catalog = inputs.catalog?.takeIf { it.projectId == credentials.projectId && it.host == credentials.host }
        val pin = catalog?.pin(config.pinId)
        val name = pin?.name ?: config.pinName ?: context.getString(R.string.chart_widget_this_pin)
        if (pin == null) {
            // Without a catalog for this project the app has not listed its pins yet, so the pin may still be there.
            return if (catalog != null) {
                Resolved.Message(null, context.getString(R.string.chart_widget_no_longer_pinned, name))
            } else {
                Resolved.Message(name, context.getString(R.string.chart_widget_loading), placeholder = true)
            }
        }
        if (!pin.eligible) return Resolved.Message(name, pin.reason ?: context.getString(R.string.chart_widget_ineligible))
        if (credentials.isExpired(inputs.now)) return Resolved.Message(name, context.getString(R.string.chart_widget_update_session))
        val snapshot = ChartStore.snapshot(context, pin.id)
        val error = ChartStore.snapshotError(context, pin.id)?.takeIf { snapshot == null || it.at >= snapshot.fetchedAt }
        when (error?.kind) {
            ErrorKind.AUTH -> return Resolved.Message(name, context.getString(R.string.chart_widget_update_session))
            ErrorKind.NOT_FOUND -> return Resolved.Message(null, context.getString(R.string.chart_widget_not_found, name))
        }
        if (snapshot == null) {
            if (error == null) return Resolved.Message(name, context.getString(R.string.chart_widget_loading), placeholder = true)
            val (message, detail) = failureText(context, error.kind)
            // Opening the insight in the app computes it; the next refresh then finds the result.
            return Resolved.Message(name, message, detail, linkPin = pin.takeIf { error.kind == ErrorKind.NO_RESULT })
        }
        if (snapshot.valueText == null && snapshot.rows.isEmpty() && snapshot.series.none { series -> series.points.any { it.value.isFinite() } }) {
            return Resolved.Message(name, context.getString(R.string.chart_widget_empty), linkPin = pin)
        }
        val extras = config.extraPinIds.asSequence()
            .filter { it != pin.id }
            .mapNotNull { catalog?.pin(it)?.takeIf { extra -> extra.eligible } }
            .take(TILES.size)
            .map { Extra(it, ChartStore.snapshot(context, it.id), ChartStore.snapshotError(context, it.id)) }
            .toList()
        return Resolved.Data(pin, snapshot, extras)
    }

    private fun stateViews(context: Context, id: Int, family: Family, state: Resolved.Message): RemoteViews {
        val views = RemoteViews(context.packageName, R.layout.chart_widget_state)
        if (state.title != null) {
            views.setTextViewText(R.id.chart_state_title, state.title)
            views.setViewVisibility(R.id.chart_state_title, View.VISIBLE)
        } else {
            views.setViewVisibility(R.id.chart_state_title, View.GONE)
        }
        views.setTextViewText(R.id.chart_state_message, state.message)
        views.setTextViewText(R.id.chart_state_detail, state.detail ?: "")
        views.setViewVisibility(R.id.chart_state_detail, if (state.detail != null) View.VISIBLE else View.GONE)
        views.setViewVisibility(R.id.chart_state_placeholder, if (state.placeholder) View.VISIBLE else View.GONE)
        val link = state.linkPin?.let { pinLink(context, it, family) } ?: "${scheme(context)}://views"
        views.setOnClickPendingIntent(R.id.chart_root, linkIntent(context, link, id, 0))
        views.setContentDescription(R.id.chart_root, listOfNotNull(state.title, state.message, state.detail).joinToString(". "))
        return views
    }

    private fun dataViews(context: Context, id: Int, family: Family, widthDp: Int, heightDp: Int, data: Resolved.Data, now: Long): RemoteViews {
        val isNumber = data.snapshot.display == "number" || (data.snapshot.series.isEmpty() && data.snapshot.rows.isEmpty() && data.snapshot.valueText != null)
        if (isNumber && data.extras.isEmpty()) return numberViews(context, id, family, data, now)
        val layout = when (family) {
            Family.SMALL -> R.layout.chart_widget_small
            Family.MEDIUM -> R.layout.chart_widget_medium
            Family.LARGE -> R.layout.chart_widget_large
        }
        val views = RemoteViews(context.packageName, layout)
        val snapshot = data.snapshot
        val m = Metrics(context)
        views.setTextViewText(R.id.chart_title, data.pin.name)
        val headline = snapshot.valueText ?: snapshot.chartValueText
        bindValue(context, views, R.id.chart_value, R.id.chart_delta, snapshot.copy(valueText = headline))
        views.setTextViewText(R.id.chart_range, snapshot.rangeLabel ?: "")
        val displayed = listOf(snapshot) + if (family == Family.LARGE) {
            data.extras.mapNotNull { it.snapshot.visibleAfter(it.error) }
        } else emptyList()
        val age = max(0L, now - displayed.minOf { it.updatedAt() })
        val updated = ageText(context, age)
        views.setTextViewText(R.id.chart_updated, updated)
        setTextColor(context, views, R.id.chart_updated, if (age > STALE_MS) R.color.chart_widget_orange else R.color.chart_widget_tertiary)
        val inlineAge = family != Family.SMALL && snapshot.rows.isEmpty() && snapshot.series.isNotEmpty()
        if (family != Family.SMALL) {
            views.setTextViewText(R.id.chart_age_inline, if (inlineAge) updated.removePrefix("Updated ") else "")
            views.setViewVisibility(R.id.chart_footer, if (inlineAge) View.GONE else View.VISIBLE)
        }

        val widthPx = widthDp * m.density
        val heightPx = heightDp * m.density
        val chartWidth: Float
        var chartHeight: Float
        if (family == Family.SMALL) {
            chartWidth = widthPx - m.dp(24f)
            chartHeight = heightPx - m.dp(24f) - m.line(12f) - m.dp(2f) - m.line(28f) - m.dp(2f) - m.pill() - m.dp(6f) - m.dp(4f) - m.line(10.5f)
            if (headline == null) chartHeight += m.line(28f) + m.dp(2f)
        } else {
            chartWidth = widthPx - m.dp(28f)
            val headlineHeight = if (headline != null) max(m.line(28f), m.pill()) else m.line(10.5f)
            chartHeight = heightPx - m.dp(28f) - max(m.dp(12f), m.line(12f)) - m.dp(2f) - headlineHeight - m.dp(8f) - m.dp(6f) - m.line(10.5f)
            bindHeadline(context, views, snapshot)
        }
        if (inlineAge) chartHeight += m.line(10.5f) + m.dp(6f)
        if (family == Family.LARGE) {
            if (data.extras.isNotEmpty()) {
                chartHeight -= m.dp(10f) + m.dp(20f) + m.line(12f) + m.dp(1f) + m.line(10.5f) + m.dp(4f) + max(m.line(20f), m.pill()) + m.dp(6f) + m.dp(28f)
            }
        }
        val spec = specOf(snapshot, if (family == Family.SMALL) SHORT_POINTS else TrendsParser.MAX_POINTS, grid = family != Family.SMALL)
        if (snapshot.rows.isNotEmpty()) {
            bindRows(context, views, R.id.chart_frame, R.id.chart_image_light, R.id.chart_image_dark, snapshot.rows, chartWidth, chartHeight, m.density)
        } else {
            bindChart(context, views, R.id.chart_frame, R.id.chart_image_light, R.id.chart_image_dark, spec, chartWidth, chartHeight, m.density)
        }
        if (family == Family.LARGE) bindLarge(context, views, id, data, chartWidth, m)

        views.setOnClickPendingIntent(R.id.chart_root, linkIntent(context, pinLink(context, data.pin, family), id, 0))
        val pill = snapshot.deltaText?.let { arrow(snapshot.deltaSign) + it }
        views.setContentDescription(
            R.id.chart_root,
            listOfNotNull(data.pin.name, headline, pill, snapshot.rangeLabel, snapshot.rows.joinToString(". ") { "${it.label}: ${it.value}" }.takeIf { it.isNotEmpty() }, updated).joinToString(", "),
        )
        return views
    }

    private fun numberViews(context: Context, id: Int, family: Family, data: Resolved.Data, now: Long): RemoteViews {
        val views = RemoteViews(context.packageName, R.layout.chart_widget_number)
        val snapshot = data.snapshot
        views.setTextViewText(R.id.chart_title, data.pin.name)
        bindValue(context, views, R.id.chart_value, R.id.chart_delta, snapshot)
        views.setTextViewText(R.id.chart_basis, snapshot.deltaBasis ?: snapshot.rangeLabel ?: "")
        val age = max(0L, now - (snapshot.lastRefreshAt?.let(DateText::parseInstant) ?: snapshot.fetchedAt))
        val updated = ageText(context, age)
        views.setTextViewText(R.id.chart_updated, updated)
        setTextColor(context, views, R.id.chart_updated, if (age > STALE_MS) R.color.chart_widget_orange else R.color.chart_widget_tertiary)
        views.setOnClickPendingIntent(R.id.chart_root, linkIntent(context, pinLink(context, data.pin, family), id, 0))
        views.setContentDescription(R.id.chart_root, listOfNotNull(data.pin.name, snapshot.valueText, snapshot.deltaText, snapshot.deltaBasis, updated).joinToString(", "))
        return views
    }

    private fun bindHeadline(context: Context, views: RemoteViews, snapshot: ChartSnapshot) {
        val current = snapshot.series.filter { !it.previous }
        if (snapshot.valueText != null || current.size < 2) {
            views.setViewVisibility(R.id.chart_legend, View.GONE)
            val basis = if (snapshot.valueText == null && snapshot.chartValueText != null) context.getString(R.string.chart_widget_latest) else snapshot.deltaBasis?.takeIf { snapshot.valueText != null && snapshot.deltaText != null }
            views.setTextViewText(R.id.chart_basis, basis ?: "")
            views.setViewVisibility(R.id.chart_basis, if (basis != null) View.VISIBLE else View.GONE)
            return
        }
        views.setViewVisibility(R.id.chart_value_row, View.GONE)
        // Spans cannot follow the launcher's night mode, so the legend dots use the current mode's palette.
        val palette = ChartColors.of(context, isNight(context)).series
        val legend = SpannableStringBuilder()
        current.take(TrendsParser.MAX_SERIES).forEachIndexed { index, series ->
            if (index > 0) legend.append("   ")
            val start = legend.length
            legend.append("■")
            legend.setSpan(ForegroundColorSpan(palette[index % palette.size]), start, legend.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            legend.append(" ").append(series.label)
        }
        views.setTextViewText(R.id.chart_legend, legend)
        views.setViewVisibility(R.id.chart_legend, View.VISIBLE)
    }

    private fun bindLarge(context: Context, views: RemoteViews, id: Int, data: Resolved.Data, chartWidth: Float, m: Metrics) {
        views.setViewVisibility(R.id.chart_axis, View.GONE)
        if (data.extras.isEmpty()) {
            views.setViewVisibility(R.id.chart_tiles, View.GONE)
            return
        }
        views.setViewVisibility(R.id.chart_tiles, View.VISIBLE)
        val tileWidth = (if (data.extras.size > 1) (chartWidth - m.dp(8f)) / 2 else chartWidth) - m.dp(20f)
        TILES.forEachIndexed { index, ids ->
            val extra = data.extras.getOrNull(index)
            if (extra == null) {
                views.setViewVisibility(ids.root, View.GONE)
                return@forEachIndexed
            }
            val pin = extra.pin
            val snapshot = extra.snapshot.visibleAfter(extra.error)
            views.setViewVisibility(ids.root, View.VISIBLE)
            views.setTextViewText(ids.title, pin.name)
            views.setOnClickPendingIntent(ids.root, linkIntent(context, pinLink(context, pin, Family.LARGE), id, index + 1))
            if (snapshot == null) {
                val status = extra.error?.let { failureText(context, it.kind).first } ?: context.getString(R.string.chart_widget_loading)
                views.setTextViewText(ids.range, status)
                views.setViewVisibility(ids.value, View.GONE)
                views.setViewVisibility(ids.delta, View.GONE)
                views.setViewVisibility(ids.frame, View.GONE)
                return@forEachIndexed
            }
            views.setTextViewText(ids.range, snapshot.rangeLabel ?: "")
            bindValue(context, views, ids.value, ids.delta, snapshot)
            val sparkline = specOf(snapshot, SHORT_POINTS, grid = false)
            if (snapshot.rows.isNotEmpty()) {
                bindRows(context, views, ids.frame, ids.light, ids.dark, snapshot.rows, tileWidth, m.dp(28f), m.density)
            } else {
                bindChart(context, views, ids.frame, ids.light, ids.dark, sparkline, tileWidth, m.dp(28f), m.density)
            }
        }
    }

    private fun bindValue(context: Context, views: RemoteViews, valueId: Int, deltaId: Int, snapshot: ChartSnapshot) {
        val value = snapshot.valueText
        if (value == null) {
            views.setViewVisibility(valueId, View.GONE)
            views.setViewVisibility(deltaId, View.GONE)
            return
        }
        views.setViewVisibility(valueId, View.VISIBLE)
        views.setTextViewText(valueId, value)
        val delta = snapshot.deltaText
        if (delta == null) {
            views.setViewVisibility(deltaId, View.GONE)
            return
        }
        views.setViewVisibility(deltaId, View.VISIBLE)
        views.setTextViewText(deltaId, arrow(snapshot.deltaSign) + delta)
        val (background, color) = when (snapshot.deltaSign) {
            1 -> R.drawable.chart_widget_pill_up to R.color.chart_widget_green
            -1 -> R.drawable.chart_widget_pill_down to R.color.chart_widget_red
            else -> R.drawable.chart_widget_pill_flat to R.color.chart_widget_secondary
        }
        views.setInt(deltaId, "setBackgroundResource", background)
        setTextColor(context, views, deltaId, color)
    }

    private fun arrow(sign: Int): String = when (sign) {
        1 -> "▲ "
        -1 -> "▼ "
        else -> ""
    }

    private fun specOf(snapshot: ChartSnapshot, maxPoints: Int, grid: Boolean): ChartSpec? {
        val current = snapshot.series.filter { !it.previous }.take(TrendsParser.MAX_SERIES)
        val length = current.firstOrNull()?.points?.size ?: return null
        if (length == 0) return null
        val start = max(0, length - maxPoints)
        val values = current.map { series -> series.points.take(length).drop(start).map { it.value } }
        val bars = snapshot.chartKind == "bar"
        val previous = snapshot.series.firstOrNull { it.previous }
            ?.takeIf { current.size == 1 && !bars }
            ?.points?.take(length)?.drop(start)?.map { it.value }
        val first = current.firstOrNull()?.points?.take(length)?.drop(start)
        return ChartSpec(values, previous, bars, snapshot.inProgress, grid,
            snapshot.axisLowText, snapshot.axisHighText,
            first?.firstOrNull()?.let { DateText.axisDate(it.at, snapshot.intervalLabel) },
            first?.lastOrNull()?.let { DateText.axisDate(it.at, snapshot.intervalLabel) })
    }

    /** Draws the chart for both themes; the layout shows the one that matches the launcher's night mode. */
    private fun bindChart(
        context: Context,
        views: RemoteViews,
        frameId: Int,
        lightId: Int,
        darkId: Int,
        spec: ChartSpec?,
        widthPx: Float,
        heightPx: Float,
        density: Float,
    ) {
        val fits = heightPx >= MIN_CHART_DP * density && widthPx >= MIN_CHART_DP * density
        val light = if (spec != null && fits) ChartCanvas.draw(spec, ChartColors.of(context, false), widthPx.toInt(), heightPx.toInt(), density) else null
        val dark = if (spec != null && light != null) ChartCanvas.draw(spec, ChartColors.of(context, true), widthPx.toInt(), heightPx.toInt(), density) else null
        if (light == null || dark == null) {
            views.setViewVisibility(frameId, View.GONE)
            return
        }
        views.setViewVisibility(frameId, View.VISIBLE)
        views.setImageViewBitmap(lightId, light)
        views.setImageViewBitmap(darkId, dark)
    }

    private fun bindRows(context: Context, views: RemoteViews, frameId: Int, lightId: Int, darkId: Int,
        rows: List<SnapshotRow>, width: Float, height: Float, density: Float) {
        val light = ChartCanvas.rows(rows, ChartColors.of(context, false), width.toInt(), height.toInt(), density)
        val dark = ChartCanvas.rows(rows, ChartColors.of(context, true), width.toInt(), height.toInt(), density)
        if (light == null || dark == null) { views.setViewVisibility(frameId, View.GONE); return }
        views.setViewVisibility(frameId, View.VISIBLE)
        views.setImageViewBitmap(lightId, light)
        views.setImageViewBitmap(darkId, dark)
    }

    /** From Android 12 the launcher picks the color for its own night mode; before that, the current mode decides. */
    private fun setTextColor(context: Context, views: RemoteViews, viewId: Int, colorRes: Int) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val light = ChartColors.themed(context, false).getColor(colorRes)
            val dark = ChartColors.themed(context, true).getColor(colorRes)
            views.setColorInt(viewId, "setTextColor", light, dark)
        } else {
            views.setTextColor(viewId, context.getColor(colorRes))
        }
    }

    private fun isNight(context: Context): Boolean =
        (context.resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK) ==
            android.content.res.Configuration.UI_MODE_NIGHT_YES

    private fun ageText(context: Context, ageMs: Long): String {
        if (ageMs < 60_000) return context.getString(R.string.chart_widget_updated_just_now)
        val minutes = ageMs / 60_000
        if (minutes < 60) return context.getString(R.string.chart_widget_updated_minutes, minutes.toInt())
        val hours = minutes / 60
        if (hours < 24) return context.getString(R.string.chart_widget_updated_hours, hours.toInt())
        val days = hours / 24
        return if (days == 1L) context.getString(R.string.chart_widget_updated_one_day)
        else context.getString(R.string.chart_widget_updated_days, days.toInt())
    }

    // Mirrors src/lib/appVariants.json: each build variant appends its idSuffix to the package and has its own scheme.
    private val SCHEMES = listOf(".dev" to "posthog-dev", ".preview" to "posthog-preview")

    fun scheme(context: Context): String =
        SCHEMES.firstOrNull { context.packageName.endsWith(it.first) }?.second ?: "posthog"

    /** The deep links in docs/VIEWS.md "Routes"; `family` lets the app report which widget size was tapped. */
    private fun pinLink(context: Context, pin: CatalogPin, family: Family): String {
        val scheme = scheme(context)
        val query = "from=widget&family=${family.key}"
        val dashboardId = pin.dashboardId
        val shortId = pin.shortId
        return when {
            pin.isDashboard && dashboardId != null -> "$scheme://views/dashboard/$dashboardId?$query"
            shortId != null -> "$scheme://views/insight/${Uri.encode(shortId)}?$query"
            else -> "$scheme://views"
        }
    }

    private fun linkIntent(context: Context, link: String, widgetId: Int, slot: Int): PendingIntent {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(link))
            .setPackage(context.packageName)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return PendingIntent.getActivity(
            context,
            widgetId * 4 + slot,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
    }

    /** Text heights in px, so the chart bitmap matches the room the text leaves at the user's font size. */
    private class Metrics(context: Context) {
        private val display = context.resources.displayMetrics
        val density: Float = display.density
        fun dp(value: Float): Float = value * density
        fun line(sp: Float): Float = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, sp, display) * 1.18f
        fun pill(): Float = line(10.5f) + dp(3f)
    }
}
