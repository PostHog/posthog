import io
from collections.abc import Iterator


class ClosingRawStream(io.BytesIO):
    """Stands in for urllib3's raw stream, which closes itself once the body is consumed.

    A plain ``BytesIO`` stays open at EOF, so it hides a reader that looks past the end of
    the body, which is what a csv reader always does. Assign it to ``Response.raw``, and
    ``iter_content`` streams it the way it streams a real response.

    A read after the close returns no bytes rather than raising, which is what urllib3 does.
    So a reader that calls ``read`` sees EOF, and only a reader that checks ``closed`` first,
    like ``io.TextIOWrapper``, reports the closed stream as an error.
    """

    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self._length = len(body)

    def read(self, size: int | None = -1) -> bytes:
        if self.closed:
            return b""
        data = super().read(size)
        if self.tell() >= self._length:
            self.close()
        return data

    def read1(self, size: int | None = -1) -> bytes:
        return self.read(size)

    def stream(self, amt: int, decode_content: bool = True) -> Iterator[bytes]:
        while not self.closed:
            chunk = self.read(amt)
            if not chunk:
                return
            yield chunk
