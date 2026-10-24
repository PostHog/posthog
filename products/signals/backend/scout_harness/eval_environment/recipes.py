from __future__ import annotations

import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Self
from uuid import UUID, uuid4, uuid5

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from products.posthog_ai.eval_harness.environment.schema import EVENT_TABLE, EnvironmentEvent, EnvironmentModel


class EventGroupRecipe(EnvironmentModel):
    key: str = Field(min_length=1)
    event: str = Field(min_length=1)
    count: int = Field(ge=1)
    start: AwareDatetime
    end: AwareDatetime
    properties: dict[str, JsonValue] = Field(default_factory=dict)
    organization_properties: list[str] = Field(min_length=1)
    organization_frequencies: dict[str, int]
    samples: list[EnvironmentEvent] = Field(default_factory=list)
    generated_timestamps: list[AwareDatetime]

    def organization(self, event: EnvironmentEvent) -> str:
        values = set()
        for key in self.organization_properties:
            value = event.properties.get(key)
            if value is None or value == "":
                continue
            if not isinstance(value, str):
                raise ValueError("Sample organization identifiers must be strings.")
            values.add(value)
        if len(values) != 1:
            raise ValueError("Each sample must identify exactly one organization through the declared properties.")
        value = next(iter(values))
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.start >= self.end:
            raise ValueError("Event group bounds must form a nonempty half-open interval.")
        if any(not key or count < 1 for key, count in self.organization_frequencies.items()):
            raise ValueError("Organization frequencies require nonempty identifiers and positive counts.")
        if sum(self.organization_frequencies.values()) != self.count:
            raise ValueError("Organization frequencies must sum to the group count.")
        if len(self.samples) + len(self.generated_timestamps) != self.count:
            raise ValueError("Every unknown event requires an explicit generated timestamp.")
        if len({sample.uuid for sample in self.samples}) != len(self.samples):
            raise ValueError("Observed samples must have unique event UUIDs.")
        observed = Counter(self.organization(sample) for sample in self.samples)
        if any(count > self.organization_frequencies.get(key, 0) for key, count in observed.items()):
            raise ValueError("Organization frequencies cannot discard observed sample occurrences.")
        for sample in self.samples:
            if sample.event != self.event:
                raise ValueError("Observed sample event names must match their group.")
        if any(
            not self.start <= timestamp < self.end
            for timestamp in [*self.generated_timestamps, *(sample.timestamp for sample in self.samples)]
        ):
            raise ValueError("Event timestamps must stay within their group's half-open bounds.")
        return self


class EventRecipe(EnvironmentModel):
    namespace: UUID
    source_cutoff: AwareDatetime
    groups: list[EventGroupRecipe] = Field(min_length=1)
    generated_property_omissions: dict[str, list[UUID]] = Field(default_factory=dict)
    generated_uuid_version: Literal[5, 7] = 5

    @model_validator(mode="after")
    def validate_cutoff(self) -> Self:
        if len({group.key for group in self.groups}) != len(self.groups):
            raise ValueError("Recipe group keys must be unique.")
        for group in self.groups:
            if group.end > self.source_cutoff or any(
                sample.created_at >= self.source_cutoff for sample in group.samples
            ):
                raise ValueError("Recipes cannot generate or retain events at or after the source cutoff.")
        return self

    def _generated_uuid(self, group: str, index: int, timestamp: datetime) -> UUID:
        identifier = uuid5(self.namespace, f"{group}:{index}")
        if self.generated_uuid_version == 5:
            return identifier
        milliseconds = (timestamp - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1)
        if not 0 <= milliseconds < 1 << 48:
            raise ValueError("Generated UUIDv7 timestamps must fit the unsigned 48-bit Unix millisecond range.")
        random_a = (identifier.int >> 64) & 0xFFF
        random_b = identifier.int & ((1 << 62) - 1)
        return UUID(int=(milliseconds << 80) | (7 << 76) | (random_a << 64) | (2 << 62) | random_b)

    def events(self) -> list[EnvironmentEvent]:
        events = []
        for group in self.groups:
            events.extend(group.samples)
            observed = Counter(group.organization(sample) for sample in group.samples)
            organizations = [
                organization
                for organization, count in sorted(group.organization_frequencies.items())
                for _ in range(count - observed[organization])
            ]
            for index, (timestamp, organization) in enumerate(
                zip(group.generated_timestamps, organizations, strict=True)
            ):
                identifier = self._generated_uuid(group.key, index, timestamp)
                properties = dict(group.properties)
                properties.update(dict.fromkeys(group.organization_properties, organization))
                events.append(
                    EnvironmentEvent(
                        uuid=identifier,
                        event=group.event,
                        timestamp=timestamp,
                        created_at=timestamp,
                        distinct_id=str(uuid5(self.namespace, f"distinct:{identifier}")),
                        properties=properties,
                    )
                )
        if len({event.uuid for event in events}) != len(events):
            raise ValueError("Generated UUIDs collide with observed samples or another recipe group.")
        observed_ids = {sample.uuid for group in self.groups for sample in group.samples}
        generated_ids = {event.uuid for event in events} - observed_ids
        omissions = {name: set(identifiers) for name, identifiers in self.generated_property_omissions.items()}
        if any(not name or not identifiers <= generated_ids for name, identifiers in omissions.items()):
            raise ValueError("Property omissions must name a property and refer only to generated events.")
        if omissions:
            events = [
                event.model_copy(
                    update={
                        "properties": {
                            name: value
                            for name, value in event.properties.items()
                            if event.uuid not in omissions.get(name, set())
                        }
                    }
                )
                for event in events
            ]
        return sorted(events, key=lambda event: (event.timestamp, event.uuid))

    def write_events(self, path: Path) -> None:
        events = self.events()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"The events file already exists: {path}")
        temporary = path.with_name(f".{path.stem}.{uuid4().hex}.parquet")
        with temporary.open("xb"):
            temporary.chmod(0o600)
        try:
            EVENT_TABLE.write(temporary, events)
            # A hard link publishes only a complete file and still refuses to replace an existing one.
            os.link(temporary, path)
        finally:
            temporary.unlink()
