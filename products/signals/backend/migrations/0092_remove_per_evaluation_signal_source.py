from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0091_signalscoutconfig_mcp_gateway_server_ids"),
    ]

    operations = [
        migrations.AlterField(
            model_name="signalsourceconfig",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("session_analysis_cluster", "Session analysis cluster"),
                    ("evaluation_report", "Evaluation report"),
                    ("issue", "Issue"),
                    ("ticket", "Ticket"),
                    ("issue_created", "Issue created"),
                    ("issue_reopened", "Issue reopened"),
                    ("issue_spiking", "Issue spiking"),
                    ("cross_source_issue", "Cross source issue"),
                    ("alert_state_change", "Alert state change"),
                    ("health_issue", "Health issue"),
                    ("endpoint_execution_failed", "Endpoint execution failed"),
                    (
                        "endpoint_breakdown_limit_exceeded",
                        "Endpoint breakdown limit exceeded",
                    ),
                    ("scanner_finding", "Scanner finding"),
                    ("anomaly_investigation", "Anomaly investigation"),
                    ("ci_flaky_check", "CI flaky check"),
                    ("ci_broken_default_branch", "CI broken default branch"),
                    ("ci_duration_regression", "CI duration regression"),
                ],
                max_length=100,
            ),
        ),
    ]
