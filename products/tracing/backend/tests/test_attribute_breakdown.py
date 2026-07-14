import datetime as dt

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.tests.test_keyset_pagination import DATE_FROM, DATE_TO, _b64, _TraceSpansTestBase

# CDP-style outbound POST spans hitting two destinations. Amplitude is the broken one —
# 4 of its 5 spans are errors — so a breakdown over `server.address` should surface it
# as the over-represented value among the bad spans. One span carries no attribute at
# all (groups under ''), and one lives in another service (excluded by serviceNames).
MS = 1_000_000  # ns per ms
SPANS = [
    # (service, server.address, k8s.pod.name, status_code, duration)
    ("cdp", "api2.amplitude.com", "pod-a", 2, dt.timedelta(milliseconds=100)),
    ("cdp", "api2.amplitude.com", "pod-a", 2, dt.timedelta(milliseconds=100)),
    ("cdp", "api2.amplitude.com", "pod-a", 2, dt.timedelta(milliseconds=100)),
    ("cdp", "api2.amplitude.com", "pod-a", 2, dt.timedelta(milliseconds=100)),
    ("cdp", "api2.amplitude.com", "pod-a", 0, dt.timedelta(milliseconds=100)),
    ("cdp", "api.mixpanel.com", "pod-b", 0, dt.timedelta(milliseconds=200)),
    ("cdp", "api.mixpanel.com", "pod-b", 0, dt.timedelta(milliseconds=200)),
    ("cdp", "api.mixpanel.com", "pod-b", 0, dt.timedelta(milliseconds=200)),
    ("cdp", None, "pod-b", 0, dt.timedelta(milliseconds=300)),
    ("other", "api2.amplitude.com", "pod-c", 0, dt.timedelta(milliseconds=100)),
]


class TestTraceSpansAttributeBreakdown(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()

        base = dt.datetime(2026, 6, 2, 8, 0, 0)
        rows: list[str] = []
        for i, (service, address, pod, status_code, duration) in enumerate(SPANS):
            trace_id = _b64(i.to_bytes(16, "big"))
            span_id = _b64((1000 + i).to_bytes(8, "big"))
            ts_str = base.strftime("%Y-%m-%d %H:%M:%S.%f")
            end_str = (base + duration).strftime("%Y-%m-%d %H:%M:%S.%f")
            attributes = f"map('server.address__str', '{address}')" if address else "map()"
            rows.append(
                f"('019e8758-0000-0000-0000-{i:012d}', {cls.team.id}, '{trace_id}', '{span_id}', '', "
                f"'POST', 3, '{ts_str}', '{end_str}', '{ts_str}', {status_code}, '{service}', "
                f"{attributes}, map('k8s.pod.name', '{pod}'))"
            )
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
            "resource_attributes) VALUES " + ",".join(rows)
        )

    def _breakdown(self, **query_fields) -> list[dict]:
        query: dict = {"dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO}, **query_fields}
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/attribute-breakdown/",
            {"query": query},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    @parameterized.expand(
        [
            (
                "span_attribute",
                "server.address",
                "span_attribute",
                {("api2.amplitude.com", 6, 4), ("api.mixpanel.com", 3, 0), ("", 1, 0)},
            ),
            (
                "resource_attribute",
                "k8s.pod.name",
                "span_resource_attribute",
                {("pod-a", 5, 4), ("pod-b", 4, 0), ("pod-c", 1, 0)},
            ),
        ]
    )
    def test_groups_by_attribute_value(self, _name, breakdown_key, breakdown_type, expected):
        rows = self._breakdown(breakdownKey=breakdown_key, breakdownType=breakdown_type)
        self.assertEqual(
            {(row["value"], row["count"], row["error_count"]) for row in rows},
            expected,
        )

    def test_computes_duration_quantiles(self):
        rows = self._breakdown(breakdownKey="server.address", breakdownType="span_attribute")
        by_value = {row["value"]: row for row in rows}
        # All amplitude spans run 100ms, so both quantiles sit on the constant.
        self.assertEqual(by_value["api2.amplitude.com"]["p50_duration_nano"], 100 * MS)
        self.assertEqual(by_value["api2.amplitude.com"]["p95_duration_nano"], 100 * MS)

    @parameterized.expand(
        [
            # Default order is count DESC; both rank amplitude top in this dataset.
            ("default_count_desc", {}, ("api2.amplitude.com", 4)),
            ("error_count", {"orderBy": "error_count"}, ("api2.amplitude.com", 4)),
        ]
    )
    def test_orders_by(self, _name, order_kwargs, expected_top):
        rows = self._breakdown(breakdownKey="server.address", breakdownType="span_attribute", **order_kwargs)
        self.assertEqual((rows[0]["value"], rows[0]["error_count"]), expected_top)

    def test_service_names_scope_the_breakdown(self):
        rows = self._breakdown(breakdownKey="server.address", breakdownType="span_attribute", serviceNames=["cdp"])
        by_value = {row["value"]: row["count"] for row in rows}
        self.assertEqual(by_value["api2.amplitude.com"], 5)

    def test_filter_group_scopes_the_breakdown(self):
        # The BubbleUp shape: breakdown of only the BAD spans.
        rows = self._breakdown(
            breakdownKey="server.address",
            breakdownType="span_attribute",
            filterGroup=[{"key": "status_code", "operator": "exact", "type": "span", "value": "Error"}],
        )
        self.assertEqual(
            {(row["value"], row["count"]) for row in rows},
            {("api2.amplitude.com", 4)},
        )

    @parameterized.expand(
        [
            ("service_name", {("cdp", 9, 4), ("other", 1, 0)}),
            # Int16 column: values come back stringified so the response shape stays uniform.
            ("status_code", {("2", 4, 4), ("0", 6, 0)}),
        ]
    )
    def test_span_column_breakdown(self, breakdown_key, expected):
        rows = self._breakdown(breakdownKey=breakdown_key, breakdownType="span")
        self.assertEqual(
            {(row["value"], row["count"], row["error_count"]) for row in rows},
            expected,
        )

    def test_span_column_breakdown_rejects_non_allowlisted_key(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/tracing/spans/attribute-breakdown/",
            {
                "query": {
                    "dateRange": {"date_from": DATE_FROM, "date_to": DATE_TO},
                    "breakdownKey": "timestamp",
                    "breakdownType": "span",
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    @parameterized.expand(
        [
            # Each case selects one value of the facet's own dimension; with exclusion the facet
            # must still list every value (not collapse to the selected one).
            (
                "service_names_filter",
                {"breakdownKey": "service_name", "breakdownType": "span", "serviceNames": ["other"]},
                {"cdp", "other"},
            ),
            (
                "span_column_filter",
                {
                    "breakdownKey": "status_code",
                    "breakdownType": "span",
                    "filterGroup": [{"key": "status_code", "operator": "exact", "type": "span", "value": "Error"}],
                },
                {"0", "2"},
            ),
            (
                "span_attribute_filter",
                {
                    "breakdownKey": "server.address",
                    "breakdownType": "span_attribute",
                    "filterGroup": [
                        {
                            "key": "server.address",
                            "operator": "exact",
                            "type": "span_attribute",
                            "value": "api.mixpanel.com",
                        }
                    ],
                },
                {"api2.amplitude.com", "api.mixpanel.com", ""},
            ),
            (
                "resource_attribute_filter",
                {
                    "breakdownKey": "k8s.pod.name",
                    "breakdownType": "span_resource_attribute",
                    "filterGroup": [
                        {
                            "key": "k8s.pod.name",
                            "operator": "exact",
                            "type": "span_resource_attribute",
                            "value": "pod-a",
                        }
                    ],
                },
                {"pod-a", "pod-b", "pod-c"},
            ),
        ]
    )
    def test_exclude_breakdown_filter_keeps_facet_complete(self, _name, query_fields, expected_values):
        rows = self._breakdown(excludeBreakdownFilter=True, **query_fields)
        self.assertEqual({row["value"] for row in rows}, expected_values)

    def test_exclude_breakdown_filter_keeps_other_filters(self):
        # Exclusion only drops the facet's own filter — the serviceNames scope must still apply,
        # so the amplitude span in the "other" service stays excluded (5, not 6).
        rows = self._breakdown(
            breakdownKey="server.address",
            breakdownType="span_attribute",
            serviceNames=["cdp"],
            excludeBreakdownFilter=True,
            filterGroup=[
                {"key": "server.address", "operator": "exact", "type": "span_attribute", "value": "api.mixpanel.com"}
            ],
        )
        by_value = {row["value"]: row["count"] for row in rows}
        self.assertEqual(by_value["api2.amplitude.com"], 5)
