package com.posthog.code.mobile.chart

import android.content.Context
import android.util.Log
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/** Reads one pin's insight. Only `force_cache`: the widget shows what the server already computed and never computes. */
object ChartFetcher {
    private const val TAG = "ChartWidget"
    private const val TIMEOUT_MS = 20_000

    sealed class Outcome {
        class Success(val snapshot: ChartSnapshot) : Outcome()
        class Failure(val kind: String, val retryAfterMs: Long = 60_000L) : Outcome()
    }

    fun fetch(context: Context, credentials: Credentials, pin: CatalogPin, now: Long = System.currentTimeMillis()): Outcome {
        val base = "${credentials.host}/api/projects/${credentials.projectId}/insights/"
        val insightId = pin.insightId
        val shortId = pin.shortId
        val url = when {
            insightId != null ->
                "$base$insightId/?refresh=force_cache" + (pin.dashboardId?.takeIf { pin.isDashboard }?.let { "&from_dashboard=$it" } ?: "")
            shortId != null -> "$base?short_id=${URLEncoder.encode(shortId, "UTF-8")}&refresh=force_cache"
            else -> return Outcome.Failure(ErrorKind.NOT_FOUND)
        }
        val connection = try {
            URL(url).openConnection() as HttpURLConnection
        } catch (e: IOException) {
            return Outcome.Failure(ErrorKind.NETWORK)
        }
        try {
            connection.connectTimeout = TIMEOUT_MS
            connection.readTimeout = TIMEOUT_MS
            connection.instanceFollowRedirects = false
            connection.setRequestProperty("Authorization", "Bearer ${credentials.accessToken}")
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("User-Agent", userAgent(context))
            val status = connection.responseCode
            when (status) {
                401, 403 -> return Outcome.Failure(ErrorKind.AUTH)
                404 -> return Outcome.Failure(ErrorKind.NOT_FOUND)
                429, 503 -> return Outcome.Failure(ErrorKind.RATE_LIMITED, retryAfterMs(connection.getHeaderField("Retry-After"), now))
                200 -> Unit
                else -> return Outcome.Failure(ErrorKind.NETWORK)
            }
            val body = connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            val json = JSONObject(body)
            val insight = if (insightId != null) json else findByShortId(json, shortId) ?: return Outcome.Failure(ErrorKind.NOT_FOUND)
            val queryStatus = insight.optJSONObject("query_status")
            if (queryStatus?.optString("error_code") == "rate_limited") return Outcome.Failure(ErrorKind.RATE_LIMITED)
            if (queryStatus != null && queryStatus.optBoolean("error", false)) return Outcome.Failure(ErrorKind.BAD_DATA)
            if (!insight.has("result") || insight.isNull("result")) return Outcome.Failure(ErrorKind.NO_RESULT)
            return Outcome.Success(InsightParser.parse(insight, pin, now))
        } catch (e: IOException) {
            return Outcome.Failure(ErrorKind.NETWORK)
        } catch (e: JSONException) {
            Log.w(TAG, "Pin ${pin.id} answered with JSON the widget cannot read")
            return Outcome.Failure(ErrorKind.BAD_DATA)
        } catch (e: BadDataException) {
            Log.w(TAG, "Pin ${pin.id} has an unreadable result: ${e.message}")
            return Outcome.Failure(ErrorKind.BAD_DATA)
        } finally {
            connection.disconnect()
        }
    }

    internal fun retryAfterMs(value: String?, now: Long): Long {
        val seconds = value?.trim()?.toLongOrNull()
        if (seconds != null) return seconds.coerceIn(0L, Long.MAX_VALUE / 1000L - now / 1000L).times(1000L).coerceAtLeast(60_000L)
        val retryAt = value?.let {
            runCatching {
                SimpleDateFormat("EEE, dd MMM yyyy HH:mm:ss zzz", Locale.US).apply {
                    timeZone = TimeZone.getTimeZone("GMT")
                }.parse(it)?.time
            }.getOrNull()
        }
        return ((retryAt ?: now) - now).coerceAtLeast(60_000L)
    }

    private fun findByShortId(json: JSONObject, shortId: String?): JSONObject? {
        val results = json.optJSONArray("results") ?: return null
        return (0 until results.length()).mapNotNull { results.optJSONObject(it) }.firstOrNull { it.optString("short_id") == shortId }
    }

    private fun userAgent(context: Context): String {
        val version = try {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName
        } catch (e: Exception) {
            null
        } ?: "unknown"
        return "posthog-mobile-widget/$version (android)"
    }
}
