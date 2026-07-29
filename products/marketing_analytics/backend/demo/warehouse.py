"""Cost tables for the demo world: CSV generation + warehouse registration.

Native tables use each platform's real column names (micros for Google, JSON
action arrays for Meta, unified entity+stats report for Bing) so the production
adapters read them unmodified. Table names follow the `{sourcetype}_{schema}`
convention the adapter factory autodetects.
"""

import csv
import json
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from random import Random

from posthog.models import Team

from products.marketing_analytics.backend.demo.events import InvoiceRow
from products.marketing_analytics.backend.demo.world import CAMPAIGNS, DemoCampaign
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv

DEMO_BUCKET = "marketing_demo"

CLP_PER_USD = 950

BIGQUERY_ADS_TABLE = "demo_partner_ads"
STRIPE_INVOICES_TABLE = "demo_stripe_invoices"


@dataclass
class RegisteredTable:
    name: str
    table: DataWarehouseTable


def _daily_stats(campaign: DemoCampaign, day: dt.date, rng: Random) -> tuple[float, int, int, int, float]:
    jitter = rng.uniform(0.75, 1.25)
    cost = round(campaign.daily_cost * jitter, 2)
    impressions = max(1, round(campaign.daily_impressions * jitter))
    clicks = max(0, round(campaign.daily_clicks * jitter))
    conversions = round(clicks * campaign.reported_conversion_rate)
    value = round(conversions * campaign.reported_value_per_conversion * rng.uniform(0.8, 1.2), 2)
    return cost, impressions, clicks, conversions, value


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


class CostTableBuilder:
    def __init__(self, *, seed: str, days_past: int, now: dt.datetime, out_dir: Path):
        self.rng = Random(f"{seed}-warehouse")
        self.days = [(now - dt.timedelta(days=offset)).date() for offset in range(days_past, 0, -1)]
        self.out_dir = out_dir

    def _campaigns(self, platform: str) -> list[DemoCampaign]:
        return [c for c in CAMPAIGNS if c.platform == platform and c.daily_cost > 0]

    def build_google(self) -> dict[str, Path]:
        campaigns = self._campaigns("GoogleAds")
        entity_rows = [[c.campaign_id, c.name, "ENABLED"] for c in campaigns]
        stats_rows: list[list] = []
        ad_group_rows: list[list] = []
        ad_group_stats_rows: list[list] = []
        ad_rows: list[list] = []
        ad_stats_rows: list[list] = []
        for c in campaigns:
            for day in self.days:
                cost, impressions, clicks, conversions, value = _daily_stats(c, day, self.rng)
                stats_rows.append(
                    [c.campaign_id, str(day), impressions, clicks, round(cost * 1_000_000), conversions, value, "USD"]
                )
                if c.ad_groups:
                    share = 1 / len(c.ad_groups)
                    for group in c.ad_groups:
                        ad_group_stats_rows.append(
                            [
                                group.ad_group_id,
                                str(day),
                                round(impressions * share),
                                round(clicks * share),
                                round(cost * share * 1_000_000),
                                round(conversions * share),
                                round(value * share, 2),
                                "USD",
                            ]
                        )
                        ad_share = share / len(group.ads)
                        for ad in group.ads:
                            ad_stats_rows.append(
                                [
                                    ad.ad_id,
                                    str(day),
                                    round(impressions * ad_share),
                                    round(clicks * ad_share),
                                    round(cost * ad_share * 1_000_000),
                                    round(conversions * ad_share),
                                    round(value * ad_share, 2),
                                    "USD",
                                ]
                            )
            for group in c.ad_groups:
                ad_group_rows.append([group.ad_group_id, group.name, c.campaign_id])
                for ad in group.ads:
                    ad_rows.append([ad.ad_id, ad.name, group.ad_group_id, c.campaign_id])

        stats_header = [
            "segments_date",
            "metrics_impressions",
            "metrics_clicks",
            "metrics_cost_micros",
            "metrics_conversions",
            "metrics_conversions_value",
            "customer_currency_code",
        ]
        paths = {
            "campaign": self.out_dir / "googleads_campaign.csv",
            "campaign_overview_stats": self.out_dir / "googleads_campaign_overview_stats.csv",
            "ad_group": self.out_dir / "googleads_ad_group.csv",
            "ad_group_stats": self.out_dir / "googleads_ad_group_stats.csv",
            "ad": self.out_dir / "googleads_ad.csv",
            "ad_stats": self.out_dir / "googleads_ad_stats.csv",
        }
        _write_csv(paths["campaign"], ["campaign_id", "campaign_name", "campaign_status"], entity_rows)
        _write_csv(paths["campaign_overview_stats"], ["campaign_id", *stats_header], stats_rows)
        _write_csv(paths["ad_group"], ["ad_group_id", "ad_group_name", "campaign_id"], ad_group_rows)
        _write_csv(paths["ad_group_stats"], ["ad_group_id", *stats_header], ad_group_stats_rows)
        _write_csv(paths["ad"], ["ad_group_ad_ad_id", "ad_group_ad_ad_name", "ad_group_id", "campaign_id"], ad_rows)
        _write_csv(paths["ad_stats"], ["ad_group_ad_ad_id", *stats_header], ad_stats_rows)
        return paths

    def build_meta(self) -> dict[str, Path]:
        campaigns = self._campaigns("MetaAds")
        entity_rows = [[c.campaign_id, c.name, "ACTIVE"] for c in campaigns]
        stats_rows: list[list] = []
        for c in campaigns:
            for day in self.days:
                cost, impressions, clicks, conversions, value = _daily_stats(c, day, self.rng)
                actions = json.dumps([{"action_type": "purchase", "value": str(conversions)}])
                action_values = json.dumps([{"action_type": "purchase", "value": str(value)}])
                stats_rows.append(
                    [c.campaign_id, str(day), str(day), impressions, clicks, cost, "USD", actions, action_values]
                )
        paths = {
            "campaigns": self.out_dir / "metaads_campaigns.csv",
            "campaign_stats": self.out_dir / "metaads_campaign_stats.csv",
        }
        _write_csv(paths["campaigns"], ["id", "name", "status"], entity_rows)
        _write_csv(
            paths["campaign_stats"],
            [
                "campaign_id",
                "date_start",
                "date_stop",
                "impressions",
                "clicks",
                "spend",
                "account_currency",
                "actions",
                "action_values",
            ],
            stats_rows,
        )
        return paths

    def build_bing(self) -> dict[str, Path]:
        campaigns = self._campaigns("BingAds")
        entity_rows = [[c.campaign_id, c.name, "Active"] for c in campaigns]
        stats_rows: list[list] = []
        for c in campaigns:
            for day in self.days:
                cost, impressions, clicks, conversions, value = _daily_stats(c, day, self.rng)
                stats_rows.append(
                    [c.campaign_id, c.name, str(day), impressions, clicks, cost, conversions, value, "USD"]
                )
        paths = {
            "campaigns": self.out_dir / "bingads_campaigns.csv",
            "campaign_performance_report": self.out_dir / "bingads_campaign_performance_report.csv",
        }
        _write_csv(paths["campaigns"], ["id", "name", "status"], entity_rows)
        _write_csv(
            paths["campaign_performance_report"],
            [
                "campaign_id",
                "campaign_name",
                "time_period",
                "impressions",
                "clicks",
                "spend",
                "conversions",
                "revenue",
                "currency_code",
            ],
            stats_rows,
        )
        return paths

    def build_linkedin(self) -> dict[str, Path]:
        campaigns = self._campaigns("LinkedinAds")
        entity_rows = [[c.campaign_id, c.name, "ACTIVE"] for c in campaigns]
        stats_rows: list[list] = []
        for c in campaigns:
            for day in self.days:
                cost, impressions, clicks, conversions, value = _daily_stats(c, day, self.rng)
                stats_rows.append([c.campaign_id, str(day), impressions, clicks, cost, conversions, value, "USD"])
        paths = {
            "campaign_groups": self.out_dir / "linkedinads_campaign_groups.csv",
            "campaign_group_stats": self.out_dir / "linkedinads_campaign_group_stats.csv",
        }
        _write_csv(paths["campaign_groups"], ["id", "name", "status"], entity_rows)
        _write_csv(
            paths["campaign_group_stats"],
            [
                "campaign_group_id",
                "date_start",
                "impressions",
                "clicks",
                "cost_in_usd",
                "external_website_conversions",
                "conversion_value_in_local_currency",
                "currency",
            ],
            stats_rows,
        )
        return paths

    def build_reddit(self) -> dict[str, Path]:
        campaigns = self._campaigns("RedditAds")
        entity_rows = [[c.campaign_id, c.name, "ACTIVE"] for c in campaigns]
        stats_rows: list[list] = []
        for c in campaigns:
            for day in self.days:
                cost, impressions, clicks, conversions, value = _daily_stats(c, day, self.rng)
                stats_rows.append(
                    [
                        c.campaign_id,
                        str(day),
                        impressions,
                        clicks,
                        round(cost * 1_000_000),  # micros
                        conversions,
                        round(value * 100),  # cents
                        0,
                        "USD",
                    ]
                )
        paths = {
            "campaigns": self.out_dir / "redditads_campaigns.csv",
            "campaign_report": self.out_dir / "redditads_campaign_report.csv",
        }
        _write_csv(paths["campaigns"], ["id", "name", "status"], entity_rows)
        _write_csv(
            paths["campaign_report"],
            [
                "campaign_id",
                "date",
                "impressions",
                "clicks",
                "spend",
                "key_conversion_total_count",
                "conversion_purchase_total_value",
                "conversion_signup_total_value",
                "currency",
            ],
            stats_rows,
        )
        return paths

    def build_pinterest(self) -> dict[str, Path]:
        campaigns = self._campaigns("PinterestAds")
        entity_rows = [[c.campaign_id, c.name, "ACTIVE"] for c in campaigns]
        stats_rows: list[list] = []
        for c in campaigns:
            for day in self.days:
                cost, impressions, clicks, conversions, value = _daily_stats(c, day, self.rng)
                stats_rows.append(
                    [
                        c.campaign_id,
                        str(day),
                        impressions,
                        clicks,
                        cost,  # spend_in_dollar: plain dollars
                        conversions,
                        round(value * 1_000_000),  # micro-dollars
                        "USD",
                    ]
                )
        paths = {
            "campaigns": self.out_dir / "pinterestads_campaigns.csv",
            "campaign_analytics": self.out_dir / "pinterestads_campaign_analytics.csv",
        }
        _write_csv(paths["campaigns"], ["id", "name", "status"], entity_rows)
        _write_csv(
            paths["campaign_analytics"],
            [
                "campaign_id",
                "date",
                "total_impression",
                "total_clickthrough",
                "spend_in_dollar",
                "total_conversions",
                "total_checkout_value_in_micro_dollar",
                "currency",
            ],
            stats_rows,
        )
        return paths

    def build_snapchat(self) -> dict[str, Path]:
        campaigns = self._campaigns("SnapchatAds")
        entity_rows = [[c.campaign_id, c.name, "ACTIVE"] for c in campaigns]
        stats_rows: list[list] = []
        for c in campaigns:
            for day in self.days:
                cost, impressions, clicks, conversions, value = _daily_stats(c, day, self.rng)
                stats_rows.append(
                    [
                        c.campaign_id,
                        str(day),
                        impressions,
                        clicks,  # "swipes" is Snapchat's click metric
                        round(cost * 1_000_000),  # micros
                        conversions,
                        value,
                        "USD",
                    ]
                )
        paths = {
            "campaigns": self.out_dir / "snapchatads_campaigns.csv",
            "campaign_stats_daily": self.out_dir / "snapchatads_campaign_stats_daily.csv",
        }
        _write_csv(paths["campaigns"], ["id", "name", "status"], entity_rows)
        _write_csv(
            paths["campaign_stats_daily"],
            [
                "id",
                "start_time",
                "impressions",
                "swipes",
                "spend",
                "conversion_purchases",
                "conversion_purchases_value",
                "currency",
            ],
            stats_rows,
        )
        return paths

    def build_tiktok(self) -> dict[str, Path]:
        campaigns = self._campaigns("TikTokAds")
        entity_rows = [[c.campaign_id, c.name, "CAMPAIGN_STATUS_ENABLE"] for c in campaigns]
        stats_rows: list[list] = []
        for c in campaigns:
            for day in self.days:
                cost, impressions, clicks, conversions, value = _daily_stats(c, day, self.rng)
                stats_rows.append(
                    [
                        c.campaign_id,
                        f"{day} 00:00:00",
                        impressions,
                        clicks,
                        round(cost * CLP_PER_USD, 2),
                        conversions,
                        round(value * CLP_PER_USD, 2),
                        "CLP",
                    ]
                )
        paths = {
            "campaigns": self.out_dir / "tiktokads_campaigns.csv",
            "campaign_report": self.out_dir / "tiktokads_campaign_report.csv",
        }
        _write_csv(paths["campaigns"], ["campaign_id", "campaign_name", "operation_status"], entity_rows)
        _write_csv(
            paths["campaign_report"],
            [
                "campaign_id",
                "stat_time_day",
                "impressions",
                "clicks",
                "spend",
                "conversion",
                "total_complete_payment_rate",
                "currency",
            ],
            stats_rows,
        )
        return paths

    def build_bigquery_ads(self) -> Path:
        campaigns = self._campaigns("BigQuery")
        rows: list[list] = []
        for c in campaigns:
            for day in self.days:
                cost, impressions, clicks, _conversions, _value = _daily_stats(c, day, self.rng)
                rows.append([c.campaign_id, c.name, str(day), cost, clicks, impressions])
        path = self.out_dir / f"{BIGQUERY_ADS_TABLE}.csv"
        _write_csv(path, ["campaign_id", "campaign_name", "date", "cost", "clicks", "impressions"], rows)
        return path

    def build_stripe_invoices(self, invoices: list[InvoiceRow]) -> Path:
        rows = [
            [
                inv.invoice_id,
                inv.distinct_id,
                inv.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                inv.amount,
                inv.utm_campaign,
                inv.utm_source,
            ]
            for inv in invoices
        ]
        path = self.out_dir / f"{STRIPE_INVOICES_TABLE}.csv"
        _write_csv(path, ["id", "distinct_id", "created_at", "amount", "utm_campaign", "utm_source"], rows)
        return path


STRING = "String"
FLOAT = "Float64"

GOOGLE_COLUMNS: dict[str, dict[str, str]] = {
    "campaign": {"campaign_id": STRING, "campaign_name": STRING, "campaign_status": STRING},
    "campaign_overview_stats": {
        "campaign_id": STRING,
        "segments_date": STRING,
        "metrics_impressions": FLOAT,
        "metrics_clicks": FLOAT,
        "metrics_cost_micros": FLOAT,
        "metrics_conversions": FLOAT,
        "metrics_conversions_value": FLOAT,
        "customer_currency_code": STRING,
    },
    "ad_group": {"ad_group_id": STRING, "ad_group_name": STRING, "campaign_id": STRING},
    "ad": {"ad_group_ad_ad_id": STRING, "ad_group_ad_ad_name": STRING, "ad_group_id": STRING, "campaign_id": STRING},
}
GOOGLE_COLUMNS["ad_group_stats"] = {**GOOGLE_COLUMNS["campaign_overview_stats"], "ad_group_id": STRING}
del GOOGLE_COLUMNS["ad_group_stats"]["campaign_id"]
GOOGLE_COLUMNS["ad_stats"] = {**GOOGLE_COLUMNS["campaign_overview_stats"], "ad_group_ad_ad_id": STRING}
del GOOGLE_COLUMNS["ad_stats"]["campaign_id"]

META_COLUMNS: dict[str, dict[str, str]] = {
    "campaigns": {"id": STRING, "name": STRING, "status": STRING},
    "campaign_stats": {
        "campaign_id": STRING,
        "date_start": STRING,
        "date_stop": STRING,
        "impressions": FLOAT,
        "clicks": FLOAT,
        "spend": FLOAT,
        "account_currency": STRING,
        "actions": STRING,
        "action_values": STRING,
    },
}

BING_COLUMNS: dict[str, dict[str, str]] = {
    "campaigns": {"id": STRING, "name": STRING, "status": STRING},
    "campaign_performance_report": {
        "campaign_id": STRING,
        "campaign_name": STRING,
        "time_period": STRING,
        "impressions": FLOAT,
        "clicks": FLOAT,
        "spend": FLOAT,
        "conversions": FLOAT,
        "revenue": FLOAT,
        "currency_code": STRING,
    },
}

LINKEDIN_COLUMNS: dict[str, dict[str, str]] = {
    "campaign_groups": {"id": STRING, "name": STRING, "status": STRING},
    "campaign_group_stats": {
        "campaign_group_id": STRING,
        "date_start": STRING,
        "impressions": FLOAT,
        "clicks": FLOAT,
        "cost_in_usd": FLOAT,
        "external_website_conversions": FLOAT,
        "conversion_value_in_local_currency": FLOAT,
        "currency": STRING,
    },
}

REDDIT_COLUMNS: dict[str, dict[str, str]] = {
    "campaigns": {"id": STRING, "name": STRING, "status": STRING},
    "campaign_report": {
        "campaign_id": STRING,
        "date": STRING,
        "impressions": FLOAT,
        "clicks": FLOAT,
        "spend": FLOAT,
        "key_conversion_total_count": FLOAT,
        "conversion_purchase_total_value": FLOAT,
        "conversion_signup_total_value": FLOAT,
        "currency": STRING,
    },
}

PINTEREST_COLUMNS: dict[str, dict[str, str]] = {
    "campaigns": {"id": STRING, "name": STRING, "status": STRING},
    "campaign_analytics": {
        "campaign_id": STRING,
        "date": STRING,
        "total_impression": FLOAT,
        "total_clickthrough": FLOAT,
        "spend_in_dollar": FLOAT,
        "total_conversions": FLOAT,
        "total_checkout_value_in_micro_dollar": FLOAT,
        "currency": STRING,
    },
}

SNAPCHAT_COLUMNS: dict[str, dict[str, str]] = {
    "campaigns": {"id": STRING, "name": STRING, "status": STRING},
    "campaign_stats_daily": {
        "id": STRING,
        "start_time": STRING,
        "impressions": FLOAT,
        "swipes": FLOAT,
        "spend": FLOAT,
        "conversion_purchases": FLOAT,
        "conversion_purchases_value": FLOAT,
        "currency": STRING,
    },
}

TIKTOK_COLUMNS: dict[str, dict[str, str]] = {
    "campaigns": {"campaign_id": STRING, "campaign_name": STRING, "operation_status": STRING},
    "campaign_report": {
        "campaign_id": STRING,
        "stat_time_day": STRING,
        "impressions": FLOAT,
        "clicks": FLOAT,
        "spend": FLOAT,
        "conversion": FLOAT,
        "total_complete_payment_rate": FLOAT,
        "currency": STRING,
    },
}

# platform -> (builder method name, table name prefix, columns per schema)
NATIVE_SPECS: dict[str, tuple[str, str, dict[str, dict[str, str]]]] = {
    "GoogleAds": ("build_google", "googleads", GOOGLE_COLUMNS),
    "MetaAds": ("build_meta", "metaads", META_COLUMNS),
    "BingAds": ("build_bing", "bingads", BING_COLUMNS),
    "LinkedinAds": ("build_linkedin", "linkedinads", LINKEDIN_COLUMNS),
    "RedditAds": ("build_reddit", "redditads", REDDIT_COLUMNS),
    "PinterestAds": ("build_pinterest", "pinterestads", PINTEREST_COLUMNS),
    "SnapchatAds": ("build_snapchat", "snapchatads", SNAPCHAT_COLUMNS),
    "TikTokAds": ("build_tiktok", "tiktokads", TIKTOK_COLUMNS),
}

BIGQUERY_ADS_COLUMNS = {
    "campaign_id": STRING,
    "campaign_name": STRING,
    "date": STRING,
    "cost": FLOAT,
    "clicks": FLOAT,
    "impressions": FLOAT,
}

STRIPE_INVOICES_COLUMNS = {
    "id": STRING,
    "distinct_id": STRING,
    "created_at": STRING,
    "amount": FLOAT,
    "utm_campaign": STRING,
    "utm_source": STRING,
}


def register_table(
    team: Team,
    *,
    csv_path: Path,
    table_name: str,
    columns: dict[str, str],
    source: ExternalDataSource | None,
    credential: DataWarehouseCredential | None,
) -> RegisteredTable:
    existing = DataWarehouseTable.objects.filter(team=team, name=table_name, deleted=False).first()
    if existing:
        existing_source = existing.external_data_source
        if existing_source is not None and not (existing_source.source_id or "").startswith("marketing-demo"):
            raise ValueError(
                f"Table '{table_name}' belongs to a real integration on this team - "
                "run the demo seeder against a dedicated project instead"
            )
        existing.deleted = True
        existing.save()
    table, _source, _credential, _df, _cleanup = create_data_warehouse_table_from_csv(
        csv_path,
        table_name,
        columns,
        DEMO_BUCKET,
        team,
        source=source,
        credential=credential,
        source_prefix="",
    )
    return RegisteredTable(name=table_name, table=table)
