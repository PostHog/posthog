import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

import yaml
import numpy as np

from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_TOPIC
from posthog.models import Team


class Command(BaseCommand):
    help = "Ingest pre-enriched video segments with embeddings directly into ClickHouse document_embeddings"

    def add_arguments(self, parser):
        parser.add_argument("yaml_file", type=str, help="Path to the YAML file containing enriched video segments")
        parser.add_argument("--dry-run", action="store_true", help="Print records without ingesting")
        parser.add_argument("--team-id", type=int, help="Override the team_id in the segments")

    def handle(self, *args, **options):
        yaml_file = Path(options["yaml_file"])
        dry_run = options["dry_run"]
        override_team_id = options.get("team_id")

        if not yaml_file.exists():
            raise CommandError(f"YAML file not found: {yaml_file}")

        self.stdout.write(f"Reading segments from {yaml_file}...")

        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        metadata = data.get("metadata", {})
        segments = data.get("segments", [])

        if not segments:
            raise CommandError("No segments found in YAML file")

        # Load embeddings from the .npy file
        embeddings_filename = metadata.get("embeddings_file")
        if not embeddings_filename:
            raise CommandError("No embeddings_file specified in metadata - is this an enriched YAML file?")

        embeddings_file = yaml_file.parent / embeddings_filename
        if not embeddings_file.exists():
            raise CommandError(f"Embeddings file not found: {embeddings_file}")

        self.stdout.write(f"Loading embeddings from {embeddings_file}...")
        embeddings = np.load(embeddings_file)
        self.stdout.write(f"Loaded {len(embeddings)} embeddings with shape {embeddings.shape}")

        # Determine team_id
        if override_team_id:
            team_id = override_team_id
            self.stdout.write(f"Using override team_id: {team_id}")
        else:
            team = Team.objects.order_by("-id").first()
            if not team:
                raise CommandError("No teams found in the database. Use --team-id to specify one.")
            team_id = team.id
            self.stdout.write(f"Using team: {team_id} ({team.name})")

        self.stdout.write(f"Found {len(segments)} segments")
        self.stdout.write(f"Embedding model: {metadata.get('embedding_model', 'unknown')}")
        self.stdout.write(f"Target topic: {KAFKA_DOCUMENT_EMBEDDINGS_TOPIC}")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no records will be ingested"))

        producer = KafkaProducer()
        ingested_count = 0
        skipped_count = 0

        for i, segment in enumerate(segments):
            # Get embedding index
            embedding_index = segment.get("embedding_index")
            if embedding_index is None:
                self.stdout.write(self.style.WARNING(f"Segment {i} missing embedding_index, skipping"))
                skipped_count += 1
                continue

            if embedding_index >= len(embeddings):
                self.stdout.write(
                    self.style.WARNING(f"Segment {i} has invalid embedding_index {embedding_index}, skipping")
                )
                skipped_count += 1
                continue

            # Get the embedding and convert from float32 to float64 list
            embedding = embeddings[embedding_index].astype(np.float64).tolist()

            # Parse timestamp to ClickHouse format: "YYYY-MM-DD HH:MM:SS.fff"
            timestamp_iso = segment.get("timestamp", "")
            timestamp_ch = self._format_ch_datetime(timestamp_iso)

            # Build the EmbeddingRecord matching the Rust struct
            record = {
                "team_id": team_id,
                "product": segment.get("product", "session-replay"),
                "document_type": segment.get("document_type", "video-segment"),
                "model_name": segment.get("model_name", "text-embedding-3-large-3072"),
                "rendering": segment.get("rendering", "video-analysis"),
                "document_id": segment.get("document_id", ""),
                "timestamp": timestamp_ch,
                "embedding": embedding,
                "content": segment.get("content", ""),
                "metadata": json.dumps(segment.get("metadata", {})),
            }

            if dry_run:
                if i < 3:
                    self.stdout.write(f"\nRecord {i + 1}:")
                    self.stdout.write(f"  document_id: {record['document_id']}")
                    self.stdout.write(f"  team_id: {record['team_id']}")
                    self.stdout.write(f"  timestamp: {record['timestamp']}")
                    self.stdout.write(f"  content: {record['content'][:80]}...")
                    self.stdout.write(f"  embedding: [{len(embedding)} floats]")
            else:
                producer.produce(topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC, data=record)
                ingested_count += 1

                if ingested_count % 100 == 0:
                    self.stdout.write(f"Emitted {ingested_count}/{len(segments)} records...")

        if skipped_count > 0:
            self.stdout.write(self.style.WARNING(f"Skipped {skipped_count} records"))

        if not dry_run:
            self.stdout.write("Flushing Kafka producer...")
            producer.flush()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully emitted {ingested_count} records to {KAFKA_DOCUMENT_EMBEDDINGS_TOPIC}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"DRY RUN complete - would emit {len(segments) - skipped_count} records")
            )

    def _format_ch_datetime(self, iso_timestamp: str) -> str:
        """Convert ISO timestamp to ClickHouse format: YYYY-MM-DD HH:MM:SS.fff"""
        if not iso_timestamp:
            return ""
        # Handle ISO format like "2026-01-19T09:56:49.714000+00:00"
        # Convert to "2026-01-19 09:56:49.714"
        try:
            # Remove timezone info and convert T to space
            ts = iso_timestamp.replace("T", " ")
            # Remove timezone suffix if present
            if "+" in ts:
                ts = ts.split("+")[0]
            elif ts.endswith("Z"):
                ts = ts[:-1]
            # Truncate microseconds to milliseconds (3 decimal places)
            if "." in ts:
                base, frac = ts.split(".")
                frac = frac[:3].ljust(3, "0")  # Ensure exactly 3 digits
                ts = f"{base}.{frac}"
            return ts
        except Exception:
            return iso_timestamp
