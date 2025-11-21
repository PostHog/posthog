from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.api.embedding_worker import EmbeddingKafkaRequest, insert_embeddings
from posthog.models.utils import UUIDTModel


class Signal(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    # e.g. "error_tracking", "session_replay" etc
    product = models.TextField(null=False, blank=False)
    # e.g. "new_issue", "new_fingerprint", "session_summary" etc
    signal_type = models.TextField(null=False, blank=False)
    # The ID (generally a UUID) of the signal source, e.g. an error tracking
    # issue or a session recording.
    source_id = models.TextField(null=False, blank=False)

    # Will probably usually map to the created_at of the object identified
    # by the source_id, but can also be ad-hoc
    created_at = models.DateTimeField(auto_now_add=True)

    # Particular SignalGenerators are expected to be able to, given one
    # of these, map it back to a resource within their own product that
    # can be shown to the user, queried further etc
    @property
    def path(self):
        return f"{self.product}/{self.signal_type}/{self.source_id}"

    @property
    def document_type(self):
        # For use in the embedding table
        return f"{self.product}/{self.signal_type}"


class SignalEmbedding(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    signal = models.ForeignKey("Signal", on_delete=models.CASCADE)
    # Array of the models this signal was embedded with
    model_names = ArrayField(base_field=models.TextField(), null=False, blank=False)
    rendering = models.TextField(null=False, blank=False)
    # Any associated metadata for this particular rendering. Added to the document_embeddings table
    # alongside the content and embedding, and can be used for filtering/searching later.
    metadata = models.JSONField(null=True, blank=True)
    # The actual text that was embedded
    content = models.TextField(null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def to_embedding_request(self) -> EmbeddingKafkaRequest:
        return EmbeddingKafkaRequest(
            team_id=self.team.id,
            product="signals",
            document_type=self.signal.document_type,
            rendering=self.rendering,
            document_id=self.signal.source_id,
            timestamp=self.created_at.isoformat(),  # TODO - I think this is likely to be incorrectly formatted
            contents=self.content,
            models=self.model_names,
            metadata=self.metadata,
        )

    def embed(self):
        request = self.to_embedding_request()
        insert_embeddings([request])
