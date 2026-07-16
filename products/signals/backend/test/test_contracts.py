from products.signals.backend.contracts import AnalyticsAnomalyInvestigationSignalInput


def test_anomaly_investigation_payload_matches_emitter_contract() -> None:
    AnalyticsAnomalyInvestigationSignalInput.model_validate(
        {
            "source_product": "analytics",
            "source_type": "anomaly_investigation",
            "source_id": "alert-check-id",
            "description": "Anomaly investigation completed.",
            "weight": 1,
            "extra": {
                "alert_id": "alert-id",
                "alert_name": "Signups dropped",
                "alert_check_id": "alert-check-id",
                "insight_id": "insight-id",
                "detector_type": "zscore",
                "verdict": "true_positive",
                "url": "https://app.posthog.com/notebooks/notebook-short-id",
                "insight_name": "Daily signups",
                "insight_short_id": "insight-short-id",
                "triggered_dates": ["2026-07-14", "2026-07-15"],
                "notebook_short_id": "notebook-short-id",
            },
        }
    )
