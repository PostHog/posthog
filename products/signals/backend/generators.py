from datetime import datetime
from typing import Optional

from posthog.models import Team

from products.signals.backend.models.signal import Signal, SignalEmbedding


class SignalInstance:
    def render(self) -> list[tuple[str, str]]:
        """
        Should return a list of (rendering, content) pairs
        """
        raise NotImplementedError("Subclasses must implement generate method.")

    def metadata(self) -> Optional[dict]:
        """
        Should return a dict of metadata to be stored alongside the embedding
        """
        return None

    def get_id(self) -> str:
        """
        Should return a unique ID for this source, e.g. the UUID of the session recording or error tracking issue
        """
        raise NotImplementedError("Subclasses must implement get_id method.")

    def get_timestamp(self) -> Optional[datetime]:
        """
        Should return a timestamp for this source, e.g. the created_at of the session recording or error tracking issue
        """
        return None


class SignalGenerator[T: SignalInstance]:
    product: str
    signal_type: str
    model_names: list[str]

    def backtrack(self, signal_id: str) -> T:
        """
        Given a signal ID, should return the corresponding SignalInstance
        """
        raise NotImplementedError("Subclasses must implement backtrack method.")

    def generate_single(self, source: T, team: Team) -> tuple[Signal, list[SignalEmbedding]]:
        signal, embeddings = self._generate(source, team)
        Signal.objects.bulk_create([signal])
        SignalEmbedding.objects.bulk_create(embeddings)
        for embedding in embeddings:
            embedding.embed()
        return signal, embeddings

    def generate_batch(self, to_embed: list[T], team: Team) -> list[tuple[Signal, list[SignalEmbedding]]]:
        results = []
        signals = []
        embeddings = []
        for source in to_embed:
            signal, signal_embeddings = self._generate(source, team)
            results.append((signal, signal_embeddings))
            signals.append(signal)
            embeddings.extend(signal_embeddings)

        Signal.objects.bulk_create(signals)
        SignalEmbedding.objects.bulk_create(embeddings)
        for embedding in embeddings:
            embedding.embed()
        return results

    def _generate(self, source: T, team: Team) -> tuple[Signal, list[SignalEmbedding]]:
        renderings = source.render()
        metadata = source.metadata()
        source_id = source.get_id()
        timestamp = source.get_timestamp()

        sig = Signal(
            team=team, product=self.product, signal_type=self.signal_type, source_id=source_id, created_at=timestamp
        )

        embeddings = []
        for rendering, text in renderings:
            embedding = SignalEmbedding(
                team=team,
                signal=sig,
                model_names=self.model_names,
                rendering=rendering,
                metadata=metadata,
                content=text,
                created_at=timestamp,
            )
            embeddings.append(embedding)

        return sig, embeddings
