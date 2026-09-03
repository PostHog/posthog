from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Columns every vitals metric-set table carries: the app and window the row aggregates, plus the
# version slice it was requested with.
_TIMELINE_COLUMNS: dict[str, str] = {
    "app": "Package name of the app the row belongs to (e.g. com.example.app).",
    "date": "Calendar day the aggregate covers, in Play's default reporting time zone.",
    "startTime": "Inclusive start of the aggregation window.",
    "endTime": "Exclusive end of the aggregation window.",
    "versionCode": "Version code of the app build the row is sliced by.",
    "distinctUsers": "Count of distinct users the metrics are computed over, after Play's privacy thresholding.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "crash_rate": {
        "description": (
            "Daily Android vitals crash rate: the fraction of distinct users who experienced at least "
            "one crash, sliced by app version."
        ),
        "docs_url": "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/vitals.crashrate",
        "columns": {
            **_TIMELINE_COLUMNS,
            "crashRate": "Fraction of distinct users who had at least one crash on this day.",
            "crashRate7dUserWeighted": "Crash rate over the trailing 7 days, weighted by each day's distinct users.",
            "crashRate28dUserWeighted": "Crash rate over the trailing 28 days, weighted by each day's distinct users.",
            "userPerceivedCrashRate": "Fraction of distinct users who had at least one crash while using the app.",
            "userPerceivedCrashRate7dUserWeighted": "User-perceived crash rate over the trailing 7 days.",
            "userPerceivedCrashRate28dUserWeighted": "User-perceived crash rate over the trailing 28 days.",
        },
    },
    "anr_rate": {
        "description": (
            "Daily Android vitals ANR rate: the fraction of distinct users who experienced at least one "
            "application-not-responding event, sliced by app version."
        ),
        "docs_url": "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/vitals.anrrate",
        "columns": {
            **_TIMELINE_COLUMNS,
            "anrRate": "Fraction of distinct users who had at least one ANR on this day.",
            "anrRate7dUserWeighted": "ANR rate over the trailing 7 days, weighted by each day's distinct users.",
            "anrRate28dUserWeighted": "ANR rate over the trailing 28 days, weighted by each day's distinct users.",
            "userPerceivedAnrRate": "Fraction of distinct users who had at least one ANR while using the app.",
            "userPerceivedAnrRate7dUserWeighted": "User-perceived ANR rate over the trailing 7 days.",
            "userPerceivedAnrRate28dUserWeighted": "User-perceived ANR rate over the trailing 28 days.",
        },
    },
    "excessive_wakeup_rate": {
        "description": (
            "Daily rate of sessions that woke the device more than twice an hour with alarms, sliced by app version."
        ),
        "docs_url": (
            "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/vitals.excessivewakeuprate"
        ),
        "columns": {
            **_TIMELINE_COLUMNS,
            "excessiveWakeupRate": "Fraction of distinct users whose sessions triggered excessive wakeups.",
            "excessiveWakeupRate7dUserWeighted": "Excessive wakeup rate over the trailing 7 days.",
            "excessiveWakeupRate28dUserWeighted": "Excessive wakeup rate over the trailing 28 days.",
        },
    },
    "stuck_background_wakelock_rate": {
        "description": (
            "Daily rate of sessions that held a background wakelock for longer than an hour, sliced by app version."
        ),
        "docs_url": (
            "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/"
            "vitals.stuckbackgroundwakelockrate"
        ),
        "columns": {
            **_TIMELINE_COLUMNS,
            "stuckBgWakelockRate": "Fraction of distinct users whose sessions held a stuck background wakelock.",
            "stuckBgWakelockRate7dUserWeighted": "Stuck background wakelock rate over the trailing 7 days.",
            "stuckBgWakelockRate28dUserWeighted": "Stuck background wakelock rate over the trailing 28 days.",
        },
    },
    "slow_start_rate": {
        "description": "Daily rate of app starts Play considers slow, sliced by start type and app version.",
        "docs_url": "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/vitals.slowstartrate",
        "columns": {
            **_TIMELINE_COLUMNS,
            "startType": "Start type the row is sliced by: cold, warm, or hot start.",
            "startTypeLabel": "Human-readable label for the start type.",
            "slowStartRate": "Fraction of distinct users who experienced a slow start of this type.",
            "slowStartRate7dUserWeighted": "Slow start rate over the trailing 7 days.",
            "slowStartRate28dUserWeighted": "Slow start rate over the trailing 28 days.",
        },
    },
    "slow_rendering_rate": {
        "description": (
            "Daily rate of sessions with slow frame rendering, at both the 20fps and 30fps thresholds, "
            "sliced by app version."
        ),
        "docs_url": (
            "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/vitals.slowrenderingrate"
        ),
        "columns": {
            **_TIMELINE_COLUMNS,
            "slowRenderingRate20Fps": "Fraction of distinct users whose sessions rendered slowly at the 20fps threshold.",
            "slowRenderingRate20Fps7dUserWeighted": "Slow rendering rate (20fps) over the trailing 7 days.",
            "slowRenderingRate20Fps28dUserWeighted": "Slow rendering rate (20fps) over the trailing 28 days.",
            "slowRenderingRate30Fps": "Fraction of distinct users whose sessions rendered slowly at the 30fps threshold.",
            "slowRenderingRate30Fps7dUserWeighted": "Slow rendering rate (30fps) over the trailing 7 days.",
            "slowRenderingRate30Fps28dUserWeighted": "Slow rendering rate (30fps) over the trailing 28 days.",
        },
    },
    "lmk_rate": {
        "description": (
            "Daily rate of low-memory kills the user perceived, meaning the app was killed while in use, "
            "sliced by app version."
        ),
        "docs_url": "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/vitals.lmkrate",
        "columns": {
            **_TIMELINE_COLUMNS,
            "userPerceivedLmkRate": "Fraction of distinct users whose foreground app was killed for low memory.",
            "userPerceivedLmkRate7dUserWeighted": "User-perceived low-memory kill rate over the trailing 7 days.",
            "userPerceivedLmkRate28dUserWeighted": "User-perceived low-memory kill rate over the trailing 28 days.",
        },
    },
    "error_counts": {
        "description": "Daily count of error reports Play received, sliced by report type and app version.",
        "docs_url": (
            "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/vitals.errors.counts"
        ),
        "columns": {
            **_TIMELINE_COLUMNS,
            "reportType": "Type of error the count covers: crash, ANR, or non-fatal.",
            "reportTypeLabel": "Human-readable label for the report type.",
            "errorReportCount": "Number of error reports Play received on this day for the slice.",
        },
    },
    "apps": {
        "description": "Apps the connected service account is allowed to report on.",
        "docs_url": "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/apps/search",
        "columns": {
            "name": "Resource name of the app, in the form apps/{package_name}.",
            "packageName": "Package name of the app (e.g. com.example.app).",
            "displayName": "Title of the app as shown on Google Play.",
        },
    },
    "error_issues": {
        "description": (
            "Clustered error issues (groups of similar crash, ANR, or non-fatal reports) with their report "
            "and user counts over the synced window."
        ),
        "docs_url": (
            "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/vitals.errors.issues/search"
        ),
        "columns": {
            "name": "Resource name of the issue, in the form apps/{app}/errorIssues/{id}.",
            "app": "Package name of the app the issue belongs to.",
            "type": "Issue type: crash, ANR, or non-fatal error.",
            "cause": "Cause of the issue, usually the exception or signal that triggered it.",
            "location": "Code location the issue was attributed to.",
            "errorReportCount": "Number of error reports in this issue over the requested window.",
            "distinctUsers": "Number of distinct users affected over the requested window.",
            "distinctUsersPercent": "Share of distinct users affected, relative to the app's user base.",
            "lastErrorReportTime": "Time of the most recent report in this issue.",
            "firstAppVersion": "Earliest app version the issue was reported on.",
            "lastAppVersion": "Latest app version the issue was reported on.",
            "firstOsVersion": "Earliest Android version the issue was reported on.",
            "lastOsVersion": "Latest Android version the issue was reported on.",
            "issueUri": "Deep link to the issue in Play Console.",
            "sampleErrorReports": "Resource names of a few example reports in this issue.",
            "annotations": "Play's automated annotations explaining likely causes and fixes.",
        },
    },
    "error_reports": {
        "description": "Individual crash, ANR, and non-fatal error reports, including stack traces and device details.",
        "docs_url": (
            "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/vitals.errors.reports/search"
        ),
        "columns": {
            "name": "Resource name of the report, unique across the app.",
            "app": "Package name of the app the report belongs to.",
            "type": "Report type: crash, ANR, or non-fatal error.",
            "eventTime": "Time the error occurred on the device.",
            "reportText": "Stack trace or ANR trace captured with the report.",
            "issue": "Resource name of the error issue this report was clustered into.",
            "deviceModel": "Device the report came from.",
            "osVersion": "Android version the report came from.",
            "appVersion": "App version the report came from.",
            "vcsInformation": "Version control revision the app build was made from, when the developer supplied it.",
        },
    },
    "anomalies": {
        "description": "Metric anomalies Play detected by comparing a metric against its expected range.",
        "docs_url": "https://developers.google.com/play/developer/reporting/reference/rest/v1beta1/anomalies/list",
        "columns": {
            "name": "Resource name of the anomaly.",
            "app": "Package name of the app the anomaly belongs to.",
            "metricSet": "Metric set the anomalous metric belongs to (e.g. crash rate).",
            "timelineSpec": "Aggregation period and time range the anomaly was detected over.",
            "dimensions": "Dimension values that identify the slice the anomaly was detected in.",
            "metric": "The anomalous metric, with its observed and expected values.",
        },
    },
}
