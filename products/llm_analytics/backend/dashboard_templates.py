from posthog.models.dashboard_templates import DashboardTemplate


def get_llm_analytics_default_template() -> DashboardTemplate:
    """
    Default dashboard template for LLM Analytics.
    Used when feature flag LLM_ANALYTICS_CUSTOMIZABLE_DASHBOARD is enabled.

    IMPORTANT: Keep this template in sync with frontend hardcoded tiles in
    products/llm_analytics/frontend/llmAnalyticsLogic.tsx:562-955 until full migration to customizable dashboard.
    """
    return DashboardTemplate(
        template_name="LLM Analytics Default",
        dashboard_description="Overview of your LLM usage, costs, and performance",
        dashboard_filters={"date_from": "-7d"},
        tiles=[
            {
                "type": "INSIGHT",
                "name": "Traces",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "$ai_generation",
                                "name": "$ai_generation",
                                "kind": "EventsNode",
                                "math": "hogql",
                                "math_hogql": "COUNT(DISTINCT properties.$ai_trace_id)",
                            }
                        ],
                        "dateRange": {"date_from": "-7d"},
                        "properties": [],
                        "filterTestAccounts": False,
                    },
                },
                "layouts": {
                    "sm": {"h": 5, "w": 4, "x": 0, "y": 0, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 3},
                },
            },
            {
                "type": "INSIGHT",
                "name": "Generative AI users",
                "description": "To count users, set `distinct_id` in LLM tracking.",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "$ai_generation",
                                "name": "$ai_generation",
                                "kind": "EventsNode",
                                "math": "dau",
                            }
                        ],
                        "dateRange": {"date_from": "-7d"},
                        "properties": [
                            {
                                "type": "hogql",
                                "key": "distinct_id != properties.$ai_trace_id",
                            }
                        ],
                        "filterTestAccounts": False,
                    },
                },
                "layouts": {
                    "sm": {"h": 5, "w": 4, "x": 4, "y": 0, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 5, "minH": 5, "minW": 3},
                },
            },
            {
                "type": "INSIGHT",
                "name": "Total cost (USD)",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "$ai_generation",
                                "name": "$ai_generation",
                                "math": "sum",
                                "kind": "EventsNode",
                                "math_property": "$ai_total_cost_usd",
                            }
                        ],
                        "trendsFilter": {
                            "aggregationAxisPrefix": "$",
                            "decimalPlaces": 4,
                            "display": "BoldNumber",
                        },
                        "dateRange": {
                            "date_from": "-7d",
                            "explicitDate": True,
                        },
                        "properties": [],
                        "filterTestAccounts": False,
                    },
                },
                "layouts": {
                    "sm": {"h": 5, "w": 4, "x": 8, "y": 0, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 10, "minH": 5, "minW": 3},
                },
            },
            {
                "type": "INSIGHT",
                "name": "Cost per user (USD)",
                "description": "Average cost for each generative AI user active in the data point's period.",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "$ai_generation",
                                "name": "$ai_generation",
                                "math": "sum",
                                "kind": "EventsNode",
                                "math_property": "$ai_total_cost_usd",
                            },
                            {
                                "event": "$ai_generation",
                                "name": "$ai_generation",
                                "kind": "EventsNode",
                                "math": "dau",
                            },
                        ],
                        "trendsFilter": {
                            "formula": "A / B",
                            "aggregationAxisPrefix": "$",
                            "decimalPlaces": 2,
                        },
                        "dateRange": {"date_from": "-7d"},
                        "properties": [
                            {
                                "type": "hogql",
                                "key": "distinct_id != properties.$ai_trace_id",
                            }
                        ],
                        "filterTestAccounts": False,
                    },
                },
                "layouts": {
                    "sm": {"h": 5, "w": 6, "x": 0, "y": 5, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 15, "minH": 5, "minW": 3},
                },
            },
            {
                "type": "INSIGHT",
                "name": "Cost by model (USD)",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "$ai_generation",
                                "name": "$ai_generation",
                                "math": "sum",
                                "kind": "EventsNode",
                                "math_property": "$ai_total_cost_usd",
                            }
                        ],
                        "breakdownFilter": {
                            "breakdown_type": "event",
                            "breakdown": "$ai_model",
                        },
                        "trendsFilter": {
                            "aggregationAxisPrefix": "$",
                            "decimalPlaces": 2,
                            "display": "ActionsBarValue",
                            "showValuesOnSeries": True,
                        },
                        "dateRange": {
                            "date_from": "-7d",
                            "explicitDate": True,
                        },
                        "properties": [],
                        "filterTestAccounts": False,
                    },
                },
                "layouts": {
                    "sm": {"h": 5, "w": 6, "x": 6, "y": 5, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 20, "minH": 5, "minW": 3},
                },
            },
            {
                "type": "INSIGHT",
                "name": "Generation calls",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "$ai_generation",
                                "name": "$ai_generation",
                                "kind": "EventsNode",
                            }
                        ],
                        "dateRange": {"date_from": "-7d"},
                        "properties": [],
                        "filterTestAccounts": False,
                    },
                },
                "layouts": {
                    "sm": {"h": 5, "w": 4, "x": 0, "y": 10, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 25, "minH": 5, "minW": 3},
                },
            },
            {
                "type": "INSIGHT",
                "name": "AI Errors",
                "description": "Failed AI generation calls",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "$ai_generation",
                                "name": "$ai_generation",
                                "kind": "EventsNode",
                            }
                        ],
                        "dateRange": {"date_from": "-7d"},
                        "properties": [
                            {
                                "type": "event",
                                "key": "$ai_is_error",
                                "operator": "exact",
                                "value": True,
                            }
                        ],
                        "filterTestAccounts": False,
                    },
                },
                "layouts": {
                    "sm": {"h": 5, "w": 4, "x": 4, "y": 10, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 30, "minH": 5, "minW": 3},
                },
            },
            {
                "type": "INSIGHT",
                "name": "Generation latency by model (median)",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "$ai_generation",
                                "name": "$ai_generation",
                                "math": "median",
                                "kind": "EventsNode",
                                "math_property": "$ai_latency",
                            }
                        ],
                        "breakdownFilter": {
                            "breakdown": "$ai_model",
                        },
                        "trendsFilter": {
                            "aggregationAxisPostfix": " s",
                            "decimalPlaces": 2,
                        },
                        "dateRange": {"date_from": "-7d"},
                        "properties": [],
                        "filterTestAccounts": False,
                    },
                },
                "layouts": {
                    "sm": {"h": 5, "w": 4, "x": 8, "y": 10, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 35, "minH": 5, "minW": 3},
                },
            },
            {
                "type": "INSIGHT",
                "name": "Generations by HTTP status",
                "description": "",
                "query": {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [
                            {
                                "event": "$ai_generation",
                                "name": "$ai_generation",
                                "kind": "EventsNode",
                            }
                        ],
                        "breakdownFilter": {
                            "breakdown": "$ai_http_status",
                        },
                        "trendsFilter": {
                            "display": "ActionsBarValue",
                        },
                        "dateRange": {
                            "date_from": "-7d",
                            "explicitDate": True,
                        },
                        "properties": [],
                        "filterTestAccounts": False,
                    },
                },
                "layouts": {
                    "sm": {"h": 5, "w": 4, "x": 0, "y": 15, "minH": 5, "minW": 3},
                    "xs": {"h": 5, "w": 1, "x": 0, "y": 40, "minH": 5, "minW": 3},
                },
            },
        ],
        tags=["llm-analytics"],
        scope=DashboardTemplate.Scope.GLOBAL,
        availability_contexts=["llm-analytics"],
    )
