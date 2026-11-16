package com.posthog.code.mobile.chart

import android.content.Context
import android.content.res.Configuration
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Shader
import android.text.TextPaint
import android.text.TextUtils
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/** Chart colors for one theme, read from the widget's color resources so the XML stays the only palette. */
internal class ChartColors(
    val series: List<Int>,
    val previous: Int,
    val barNeutral: Int,
    val ink: Int,
    val hairline: Int,
    val surface: Int,
) {
    companion object {
        private val SERIES = listOf(
            R.color.chart_widget_series_1,
            R.color.chart_widget_series_2,
            R.color.chart_widget_series_3,
            R.color.chart_widget_series_4,
            R.color.chart_widget_series_5,
        )
        private val cache = HashMap<Boolean, ChartColors>()
        private val contexts = HashMap<Boolean, Context>()

        @Synchronized
        fun themed(context: Context, night: Boolean): Context = contexts.getOrPut(night) {
            val config = Configuration(context.resources.configuration)
            config.uiMode = (config.uiMode and Configuration.UI_MODE_NIGHT_MASK.inv()) or
                if (night) Configuration.UI_MODE_NIGHT_YES else Configuration.UI_MODE_NIGHT_NO
            context.applicationContext.createConfigurationContext(config)
        }

        @Synchronized
        fun of(context: Context, night: Boolean): ChartColors = cache.getOrPut(night) {
            val themed = themed(context, night)
            ChartColors(
                series = SERIES.map(themed::getColor),
                previous = themed.getColor(R.color.chart_widget_previous),
                barNeutral = themed.getColor(R.color.chart_widget_bar_neutral),
                ink = themed.getColor(R.color.chart_widget_ink),
                hairline = themed.getColor(R.color.chart_widget_hairline),
                surface = themed.getColor(R.color.chart_widget_surface),
            )
        }
    }
}

/** What to draw. `current` holds up to five series of the same length; `previous` pairs with the first one. */
internal class ChartSpec(
    val current: List<List<Double>>,
    val previous: List<Double>?,
    val bars: Boolean,
    val inProgress: Boolean,
    val grid: Boolean,
    val lowLabel: String? = null,
    val highLabel: String? = null,
    val startLabel: String? = null,
    val endLabel: String? = null,
)

internal object ChartCanvas {
    private const val MAX_BITMAP_BYTES = 1.5 * 1024 * 1024

    /** Null when there is nothing to draw or no room. `density` is px per dp at the size the launcher shows. */
    fun draw(spec: ChartSpec, colors: ChartColors, widthPx: Int, heightPx: Int, density: Float): Bitmap? {
        if (widthPx <= 0 || heightPx <= 0 || spec.current.isEmpty()) return null
        // The launcher stretches the image back to the cell, so a large widget trades sharpness for memory.
        val scale = min(1.0, sqrt(MAX_BITMAP_BYTES / (widthPx.toDouble() * heightPx * 4))).toFloat()
        val width = max(1, (widthPx * scale).toInt())
        val height = max(1, (heightPx * scale).toInt())
        val dp = density * scale
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 9f * dp; color = withAlpha(colors.ink, 0.48f) }
        val labels = spec.grid && spec.lowLabel != null && spec.highLabel != null
        val right = if (labels) min(width * 0.25f, max(paint.measureText(spec.lowLabel), paint.measureText(spec.highLabel)) + 10f * dp) else 0f
        val bottom = if (spec.grid && spec.startLabel != null) 15f * dp else 0f
        val plotWidth = max(1, (width - right).toInt())
        val plotHeight = max(1, (height - bottom).toInt())
        if (spec.bars) drawBars(canvas, spec, colors, plotWidth, plotHeight, dp) else drawLines(canvas, spec, colors, plotWidth, plotHeight, dp)
        if (labels) {
            paint.textAlign = Paint.Align.RIGHT
            canvas.drawText(TextUtils.ellipsize(spec.highLabel, paint, right - 4f * dp, TextUtils.TruncateAt.END).toString(), width.toFloat(), -paint.ascent(), paint)
            if (spec.lowLabel != spec.highLabel) canvas.drawText(TextUtils.ellipsize(spec.lowLabel, paint, right - 4f * dp, TextUtils.TruncateAt.END).toString(), width.toFloat(), plotHeight.toFloat(), paint)
        }
        if (spec.grid && spec.startLabel != null) {
            paint.textAlign = Paint.Align.LEFT
            canvas.drawText(spec.startLabel, 0f, height.toFloat(), paint)
            paint.textAlign = Paint.Align.RIGHT
            canvas.drawText(spec.endLabel ?: "", plotWidth.toFloat(), height.toFloat(), paint)
        }
        return bitmap
    }

    fun rows(rows: List<SnapshotRow>, colors: ChartColors, width: Int, height: Int, density: Float): Bitmap? {
        if (width <= 0 || height <= 0) return null
        val scale = min(1.0, sqrt(MAX_BITMAP_BYTES / (width.toDouble() * height * 4))).toFloat()
        val bitmap = Bitmap.createBitmap(max(1, (width * scale).toInt()), max(1, (height * scale).toInt()), Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 11 * density * scale; color = colors.ink }
        val rowHeight = 20 * density * scale
        val limit = min(rows.size, max(1, (bitmap.height / rowHeight).toInt()))
        rows.take(limit).forEachIndexed { index, row ->
            val y = rowHeight * index - paint.ascent()
            val valueWidth = min(bitmap.width * 0.55f, paint.measureText(row.value))
            val value = TextUtils.ellipsize(row.value, paint, valueWidth, TextUtils.TruncateAt.END).toString()
            val label = TextUtils.ellipsize(row.label, paint, bitmap.width - valueWidth - 8 * density * scale, TextUtils.TruncateAt.END).toString()
            canvas.drawText(label, 0f, y, paint)
            canvas.drawText(value, bitmap.width - paint.measureText(value), y, paint)
        }
        return bitmap
    }

    private class Scale(val lo: Double, val hi: Double, val top: Float, val bottom: Float) {
        fun y(value: Double): Float = (bottom - (value - lo) / (hi - lo) * (bottom - top)).toFloat()
    }

    /**
     * `yAxisTicks` in src/ui/chart/chartMath.ts: bars start at zero, lines fit their values and never dip below zero
     * when every value is positive. There are no ticks to round to, so lines get twice the app's padding instead.
     */
    private fun scaleOf(values: List<Double>, bars: Boolean, top: Float, bottom: Float): Scale? {
        val finite = values.filter { it.isFinite() }
        if (finite.isEmpty()) return null
        var lo: Double
        var hi: Double
        if (bars) {
            lo = min(0.0, finite.min())
            hi = max(0.0, finite.max())
        } else {
            val span = finite.max() - finite.min()
            val pad = if (span > 0) 0.0 else abs(finite.max()) * 0.1
            lo = finite.min() - pad
            hi = finite.max() + pad
            if (finite.min() >= 0 && lo < 0) lo = 0.0
        }
        if (hi <= lo) hi = lo + 1
        return Scale(lo, hi, top, bottom)
    }

    private fun drawGrid(canvas: Canvas, colors: ChartColors, scale: Scale, width: Int, dp: Float) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = colors.hairline
            strokeWidth = max(1f, dp * 0.65f)
            pathEffect = DashPathEffect(floatArrayOf(2f * dp, 3f * dp), 0f)
        }
        for (fraction in listOf(0f, 1f)) {
            val y = scale.top + (scale.bottom - scale.top) * fraction
            canvas.drawLine(0f, y, width.toFloat(), y, paint)
        }
    }

    private fun drawLines(canvas: Canvas, spec: ChartSpec, colors: ChartColors, width: Int, height: Int, dp: Float) {
        val stroke = if (spec.grid) 2.3f * dp else 1.75f * dp
        val dot = 2.75f * dp
        val padX = dot + 1f * dp
        val scale = scaleOf(spec.current.flatten() + spec.previous.orEmpty(), false, dot + 1f * dp, height - stroke / 2 - 1f * dp) ?: return
        if (spec.grid) drawGrid(canvas, colors, scale, width, dp)
        val count = spec.current.first().size
        fun x(index: Int): Float = if (count <= 1) width / 2f else padX + index * (width - 2 * padX) / (count - 1)

        val first = spec.current.first()
        val accent = colors.series.first()
        val area = Path()
        var runStart = -1
        fun closeRun(end: Int) {
            if (runStart < 0) return
            area.lineTo(x(end), scale.bottom)
            area.lineTo(x(runStart), scale.bottom)
            area.close()
            runStart = -1
        }
        first.forEachIndexed { index, value ->
            if (!value.isFinite()) {
                closeRun(index - 1)
                return@forEachIndexed
            }
            if (runStart < 0) {
                runStart = index
                area.moveTo(x(index), scale.y(value))
            } else {
                area.lineTo(x(index), scale.y(value))
            }
        }
        closeRun(first.lastIndex)
        val areaPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.FILL
            shader = LinearGradient(0f, scale.top, 0f, scale.bottom, withAlpha(accent, 0.16f), withAlpha(accent, 0.01f), Shader.TileMode.CLAMP)
        }
        if (spec.current.size == 1) canvas.drawPath(area, areaPaint)

        spec.previous?.let { previous ->
            val paint = linePaint(colors.previous, stroke * 0.7f).apply {
                pathEffect = DashPathEffect(floatArrayOf(3f * dp, 3f * dp), 0f)
            }
            canvas.drawPath(linePath(previous, previous.size, ::x, scale), paint)
        }

        spec.current.forEachIndexed { seriesIndex, values ->
            val color = colors.series[seriesIndex % colors.series.size]
            // The bucket that contains now is incomplete, so its segment is dashed like the app's chart.
            val solidEnd = if (spec.inProgress && values.size >= 2) values.size - 1 else values.size
            canvas.drawPath(linePath(values, solidEnd, ::x, scale), linePaint(color, stroke))
            if (solidEnd < values.size) {
                val a = values[values.size - 2]
                val b = values[values.size - 1]
                if (a.isFinite() && b.isFinite()) {
                    val dashed = linePaint(color, stroke).apply { pathEffect = DashPathEffect(floatArrayOf(2.5f * dp, 2.5f * dp), 0f) }
                    canvas.drawLine(x(values.size - 2), scale.y(a), x(values.size - 1), scale.y(b), dashed)
                }
            }
        }

        val lastIndex = first.indexOfLast { it.isFinite() }
        if (lastIndex >= 0) {
            val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = accent }
            paint.color = colors.surface
            canvas.drawCircle(x(lastIndex), scale.y(first[lastIndex]), dot + dp, paint)
            paint.color = accent
            canvas.drawCircle(x(lastIndex), scale.y(first[lastIndex]), dot, paint)
        }
    }

    private fun linePath(values: List<Double>, end: Int, x: (Int) -> Float, scale: Scale): Path {
        val path = Path()
        var drawing = false
        for (index in 0 until min(end, values.size)) {
            val value = values[index]
            if (!value.isFinite()) {
                drawing = false
                continue
            }
            if (drawing) path.lineTo(x(index), scale.y(value)) else path.moveTo(x(index), scale.y(value))
            drawing = true
        }
        return path
    }

    private fun linePaint(color: Int, width: Float): Paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        this.color = color
        style = Paint.Style.STROKE
        strokeWidth = width
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }

    private fun drawBars(canvas: Canvas, spec: ChartSpec, colors: ChartColors, width: Int, height: Int, dp: Float) {
        val scale = scaleOf(spec.current.flatten(), true, if (spec.grid) 1f * dp else 0f, height.toFloat() - if (spec.grid) 1f * dp else 0f) ?: return
        if (spec.grid) drawGrid(canvas, colors, scale, width, dp)
        val count = spec.current.first().size
        val groups = spec.current.size
        val slot = width.toFloat() / max(1, count)
        val gap = max(1f, slot * if (count > 20) 0.2f else 0.28f)
        val barWidth = (slot - gap) / groups
        val radius = min(2f * dp, barWidth / 2)
        val zero = scale.y(0.0)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        for (index in 0 until count) {
            spec.current.forEachIndexed { seriesIndex, values ->
                val value = values.getOrNull(index) ?: return@forEachIndexed
                if (!value.isFinite()) return@forEachIndexed
                val left = index * slot + gap / 2 + seriesIndex * barWidth
                val y = scale.y(value)
                val top = min(y, zero)
                val bottom = max(y, zero)
                if (bottom - top < 0.5f) return@forEachIndexed
                // One series reads like the app's pin: neutral bars and the newest in ink.
                val base = if (groups == 1) (if (index == count - 1) colors.series.first() else withAlpha(colors.series.first(), 0.3f)) else colors.series[seriesIndex % colors.series.size]
                paint.color = if (spec.inProgress && index == count - 1) withAlpha(base, 0.55f) else base
                val r = min(radius, bottom - top)
                val radii = if (value >= 0) floatArrayOf(r, r, r, r, 0f, 0f, 0f, 0f) else floatArrayOf(0f, 0f, 0f, 0f, r, r, r, r)
                val bar = Path().apply { addRoundRect(left, top, left + barWidth, bottom, radii, Path.Direction.CW) }
                canvas.drawPath(bar, paint)
            }
        }
    }

    private fun withAlpha(color: Int, alpha: Float): Int =
        (color and 0x00FFFFFF) or ((((color ushr 24) and 0xFF) * alpha).toInt().coerceIn(0, 255) shl 24)
}
