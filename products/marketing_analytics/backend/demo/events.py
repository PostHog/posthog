"""Deterministic event generation for the marketing demo world.

Everything is derived from a seeded RNG so re-runs with the same seed produce
the same world. Events are written straight to ClickHouse via the Kafka
producer (`create_event`), which accepts historical timestamps.
"""

import uuid
import datetime as dt
from dataclasses import dataclass, field
from random import Random
from urllib.parse import urlencode

from posthog.models import Team
from posthog.models.event.util import create_event
from posthog.models.utils import uuid7

from products.marketing_analytics.backend.demo.world import (
    CAMPAIGNS,
    EVENT_DEMO_BOOKED,
    EVENT_PAGEVIEW,
    EVENT_PURCHASE,
    EVENT_SIGNUP,
    FREE_CHANNELS,
    SITE_URL,
    DemoCampaign,
    DemoFreeChannel,
)

PERSON_NAMESPACE = uuid.UUID("aa8e9c34-0d7a-46bc-b78b-1a4c5c6f7d01")


@dataclass
class InvoiceRow:
    invoice_id: str
    distinct_id: str
    created_at: dt.datetime
    amount: float
    utm_campaign: str
    utm_source: str


@dataclass
class GenerationResult:
    events_written: int = 0
    invoices: list[InvoiceRow] = field(default_factory=list)


class MarketingEventGenerator:
    def __init__(self, team: Team, *, seed: str, days_past: int, scale: float, now: dt.datetime):
        self.team = team
        self.rng = Random(seed)
        self.days_past = days_past
        self.scale = scale
        self.now = now
        self.result = GenerationResult()
        self._person_counter = 0

    def generate(self) -> GenerationResult:
        for day_offset in range(self.days_past, 0, -1):
            day = self.now - dt.timedelta(days=day_offset)
            for campaign in CAMPAIGNS:
                self._generate_campaign_day(campaign, day)
            for channel in FREE_CHANNELS:
                self._generate_free_channel_day(channel, day)
            self._generate_edge_cases(day)
        self._generate_journeys()
        return self.result

    # --- daily traffic ---

    def _generate_campaign_day(self, campaign: DemoCampaign, day: dt.datetime) -> None:
        for _ in range(self._daily_volume(campaign.daily_sessions, day)):
            distinct_id, person_uuid = self._new_person()
            ts = self._time_in_day(day)
            utm_source = self._pick_variant(campaign.utm_source, campaign.utm_source_variants)
            utm_campaign = self._pick_variant(
                campaign.utm_campaign or campaign.name.lower(), campaign.utm_campaign_variants
            )
            properties: dict = {
                "utm_source": utm_source,
                "utm_medium": campaign.utm_medium,
                "utm_campaign": utm_campaign,
                "utm_content": self.rng.choice(["hero_cta", "pricing_card", "footer_link"]),
                "$referring_domain": campaign.referring_domain or "$direct",
            }
            if campaign.click_id_property:
                properties[campaign.click_id_property] = uuid.uuid5(PERSON_NAMESPACE, f"click-{distinct_id}").hex
            session_id = self._pageview(distinct_id, person_uuid, ts, properties)
            self._maybe_convert(
                distinct_id,
                person_uuid,
                ts,
                campaign.signup_rate,
                campaign.purchase_rate,
                utm_campaign,
                utm_source,
                session_id=session_id,
            )

    def _generate_free_channel_day(self, channel: DemoFreeChannel, day: dt.datetime) -> None:
        for _ in range(self._daily_volume(channel.daily_sessions, day)):
            distinct_id, person_uuid = self._new_person()
            ts = self._time_in_day(day)
            properties: dict = {"$referring_domain": channel.referring_domain}
            utm_source = self._pick_variant(channel.utm_source, channel.utm_source_variants)
            if utm_source:
                properties["utm_source"] = utm_source
            if channel.utm_medium:
                properties["utm_medium"] = channel.utm_medium
            if channel.utm_campaign:
                properties["utm_campaign"] = channel.utm_campaign
            if channel.click_id_property:
                properties[channel.click_id_property] = uuid.uuid5(PERSON_NAMESPACE, f"click-{distinct_id}").hex
            properties.update(channel.extra_properties)
            session_id = self._pageview(distinct_id, person_uuid, ts, properties)
            self._maybe_convert(
                distinct_id,
                person_uuid,
                ts,
                channel.signup_rate,
                channel.purchase_rate,
                channel.utm_campaign or "",
                utm_source or "",
                session_id=session_id,
            )

    def _generate_edge_cases(self, day: dt.datetime) -> None:
        # Purchases whose utm_source matches no integration: feeds the
        # "Non-integrated conversions" table and the unmatched goal split.
        if day.weekday() in (1, 4):
            distinct_id, person_uuid = self._new_person()
            ts = self._time_in_day(day)
            self._purchase(
                distinct_id,
                person_uuid,
                ts,
                amount=round(self.rng.uniform(40, 120), 2),
                utm_campaign="mystery_blast",
                utm_source="some_unknown_source",
            )
        # Purchases with no UTMs and no prior pageview: organic fallback + "without UTM" split.
        if day.weekday() == 2:
            distinct_id, person_uuid = self._new_person()
            ts = self._time_in_day(day)
            self._purchase(distinct_id, person_uuid, ts, amount=round(self.rng.uniform(30, 90), 2))

    # --- multi-touch journeys ---

    def _generate_journeys(self) -> None:
        week_starts = [self.now - dt.timedelta(days=offset) for offset in range(self.days_past, 6, -7)]
        for week_start in week_starts:
            self._journey_paid_social_to_search(week_start)
            self._journey_organic_email_search(week_start)
            self._journey_ai_to_direct(week_start)
            self._journey_same_timestamp_touches(week_start)
        self._journey_out_of_window()

    def _journey_paid_social_to_search(self, start: dt.datetime) -> None:
        distinct_id, person_uuid = self._new_person()
        t0 = self._time_in_day(start)
        self._pageview(
            distinct_id,
            person_uuid,
            t0,
            {
                "utm_source": "facebook",
                "utm_medium": "paid-social",
                "utm_campaign": "prospecting_feed",
                "$referring_domain": "facebook.com",
            },
        )
        t1 = self._time_in_day(start + dt.timedelta(days=2))
        self._pageview(
            distinct_id,
            person_uuid,
            t1,
            {
                "utm_source": "google",
                "utm_medium": "cpc",
                "utm_campaign": "brand_search",
                "$referring_domain": "google.com",
            },
        )
        self._signup(distinct_id, person_uuid, t1 + dt.timedelta(minutes=9))
        self._purchase(
            distinct_id,
            person_uuid,
            self._time_in_day(start + dt.timedelta(days=3)),
            amount=round(self.rng.uniform(180, 320), 2),
            utm_campaign="",
            utm_source="",
        )

    def _journey_organic_email_search(self, start: dt.datetime) -> None:
        distinct_id, person_uuid = self._new_person()
        self._pageview(distinct_id, person_uuid, self._time_in_day(start), {"$referring_domain": "google.com"})
        self._pageview(
            distinct_id,
            person_uuid,
            self._time_in_day(start + dt.timedelta(days=3)),
            {
                "utm_source": "newsletter",
                "utm_medium": "email",
                "utm_campaign": "weekly_digest",
                "$referring_domain": "$direct",
            },
        )
        t2 = self._time_in_day(start + dt.timedelta(days=5))
        self._pageview(
            distinct_id,
            person_uuid,
            t2,
            {
                "utm_source": "google",
                "utm_medium": "cpc",
                "utm_campaign": "spring_sale_2026",
                "$referring_domain": "google.com",
            },
        )
        self._signup(distinct_id, person_uuid, t2 + dt.timedelta(minutes=4))
        self._purchase(
            distinct_id,
            person_uuid,
            self._time_in_day(start + dt.timedelta(days=6)),
            amount=round(self.rng.uniform(90, 210), 2),
        )

    def _journey_ai_to_direct(self, start: dt.datetime) -> None:
        distinct_id, person_uuid = self._new_person()
        self._pageview(distinct_id, person_uuid, self._time_in_day(start), {"$referring_domain": "chatgpt.com"})
        t1 = self._time_in_day(start + dt.timedelta(days=2))
        self._pageview(distinct_id, person_uuid, t1, {"$referring_domain": "$direct"})
        self._signup(distinct_id, person_uuid, t1 + dt.timedelta(minutes=6))

    def _journey_same_timestamp_touches(self, start: dt.datetime) -> None:
        # Two touchpoints sharing an exact timestamp: exercises tie-breaking in
        # last-touch and weight normalization in multi-touch modes.
        distinct_id, person_uuid = self._new_person()
        ts = self._time_in_day(start + dt.timedelta(days=1))
        for campaign, source in (("brand_search", "google"), ("prospecting_feed", "facebook")):
            self._pageview(
                distinct_id,
                person_uuid,
                ts,
                {"utm_source": source, "utm_medium": "cpc", "utm_campaign": campaign, "$referring_domain": "$direct"},
            )
        self._signup(distinct_id, person_uuid, ts + dt.timedelta(hours=1))

    def _journey_out_of_window(self) -> None:
        # Touchpoint > attribution window (30d) before the conversion: the
        # conversion must fall back to organic/organic.
        if self.days_past < 40:
            return
        distinct_id, person_uuid = self._new_person()
        touch_ts = self.now - dt.timedelta(days=self.days_past - 1)
        self._pageview(
            distinct_id,
            person_uuid,
            touch_ts,
            {
                "utm_source": "google",
                "utm_medium": "cpc",
                "utm_campaign": "brand_search",
                "$referring_domain": "google.com",
            },
        )
        self._purchase(
            distinct_id,
            person_uuid,
            touch_ts + dt.timedelta(days=38),
            amount=150.0,
        )

    # --- primitives ---

    def _daily_volume(self, base: int, day: dt.datetime) -> int:
        if base <= 0:
            return 0
        weekday_factor = 0.7 if day.weekday() >= 5 else 1.0
        jitter = self.rng.uniform(0.8, 1.2)
        return max(1, round(base * self.scale * weekday_factor * jitter))

    def _time_in_day(self, day: dt.datetime) -> dt.datetime:
        return day.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(
            seconds=self.rng.randint(6 * 3600, 22 * 3600)
        )

    def _new_person(self) -> tuple[str, uuid.UUID]:
        self._person_counter += 1
        distinct_id = f"mkt-demo-{self._person_counter}"
        return distinct_id, uuid.uuid5(PERSON_NAMESPACE, distinct_id)

    def _pick_variant(self, base: str | None, variants: dict[str, float]) -> str | None:
        if base is None:
            return None
        roll = self.rng.random()
        cumulative = 0.0
        for variant, share in variants.items():
            cumulative += share
            if roll < cumulative:
                return variant
        return base

    def _maybe_convert(
        self,
        distinct_id: str,
        person_uuid: uuid.UUID,
        ts: dt.datetime,
        signup_rate: float,
        purchase_rate: float,
        utm_campaign: str | None,
        utm_source: str | None,
        session_id: str | None = None,
    ) -> None:
        if self.rng.random() < signup_rate:
            self._signup(
                distinct_id, person_uuid, ts + dt.timedelta(minutes=self.rng.randint(2, 25)), session_id=session_id
            )
            if self.rng.random() < 0.04:
                self._emit(
                    distinct_id,
                    person_uuid,
                    EVENT_DEMO_BOOKED,
                    ts + dt.timedelta(hours=self.rng.randint(1, 8)),
                    {"plan": self.rng.choice(["scale", "enterprise"])},
                )
        if self.rng.random() < purchase_rate:
            self._purchase(
                distinct_id,
                person_uuid,
                ts + dt.timedelta(hours=self.rng.randint(1, 20)),
                amount=round(self.rng.uniform(50, 400), 2),
                utm_campaign=utm_campaign,
                utm_source=utm_source,
            )

    def _pageview(self, distinct_id: str, person_uuid: uuid.UUID, ts: dt.datetime, properties: dict) -> str:
        utm_params = {k: v for k, v in properties.items() if k.startswith("utm_") and v}
        url = SITE_URL + ("/?" + urlencode(utm_params) if utm_params else "/")
        session_id = self._new_session_id(ts)
        self._emit(
            distinct_id, person_uuid, EVENT_PAGEVIEW, ts, {**properties, "$current_url": url}, session_id=session_id
        )
        return session_id

    def _signup(self, distinct_id: str, person_uuid: uuid.UUID, ts: dt.datetime, session_id: str | None = None) -> None:
        self._emit(distinct_id, person_uuid, EVENT_SIGNUP, ts, {}, session_id=session_id)

    def _purchase(
        self,
        distinct_id: str,
        person_uuid: uuid.UUID,
        ts: dt.datetime,
        *,
        amount: float,
        utm_campaign: str | None = None,
        utm_source: str | None = None,
    ) -> None:
        properties: dict = {"revenue": amount, "currency": "USD"}
        if utm_campaign:
            properties["utm_campaign"] = utm_campaign
        if utm_source:
            properties["utm_source"] = utm_source
        self._emit(distinct_id, person_uuid, EVENT_PURCHASE, ts, properties)
        # A slice of purchases also lands in the fake Stripe invoices warehouse
        # table, backing the DataWarehouseNode conversion goal.
        if self.rng.random() < 0.6:
            self.result.invoices.append(
                InvoiceRow(
                    invoice_id=f"in_{uuid.uuid5(PERSON_NAMESPACE, f'{distinct_id}-{ts.isoformat()}').hex[:16]}",
                    distinct_id=distinct_id,
                    created_at=ts,
                    amount=amount,
                    utm_campaign=utm_campaign or "",
                    utm_source=utm_source or "",
                )
            )

    def _new_session_id(self, ts: dt.datetime) -> str:
        return str(uuid7(unix_ms_time=int(ts.timestamp() * 1000), random=self.rng))

    def _emit(
        self,
        distinct_id: str,
        person_uuid: uuid.UUID,
        event: str,
        ts: dt.datetime,
        properties: dict,
        session_id: str | None = None,
    ) -> None:
        create_event(
            event_uuid=uuid7(unix_ms_time=int(ts.timestamp() * 1000), random=self.rng),
            event=event,
            team=self.team,
            distinct_id=distinct_id,
            timestamp=ts,
            properties={"$session_id": session_id or self._new_session_id(ts), **properties},
            person_id=person_uuid,
            person_properties={"email": f"{distinct_id}@example.com"},
            person_created_at=ts,
        )
        self.result.events_written += 1
