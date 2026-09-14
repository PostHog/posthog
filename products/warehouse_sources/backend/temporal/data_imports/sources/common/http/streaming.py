import io
from collections.abc import Buffer

import requests

# Pull the body off the wire in 64 KiB reads.
CHUNK_BYTES = 1 << 16


class _ResponseByteStream(io.RawIOBase):
    """Read a streaming response body through ``iter_content`` as a binary file.

    Wrapping ``response.raw`` directly crashes on any body that holds content:
    urllib3 closes the raw stream as it reads the last byte, so a reader that then
    looks for the next line gets ``ValueError: I/O operation on closed file``
    rather than EOF. A csv reader always looks. ``iter_content`` reports the end of
    the body as EOF, and turns a dropped connection into a retryable ``requests``
    error mid-stream.
    """

    def __init__(self, response: requests.Response, chunk_size: int) -> None:
        self._response = response
        self._chunks = response.iter_content(chunk_size=chunk_size)
        self._buffer: memoryview = memoryview(b"")

    def readable(self) -> bool:
        return True

    def readinto(self, target: Buffer) -> int:
        while not self._buffer:
            try:
                self._buffer = memoryview(next(self._chunks))
            except StopIteration:
                return 0
        view = memoryview(target).cast("B")
        take = min(len(view), len(self._buffer))
        view[:take] = self._buffer[:take]
        # A memoryview slice is a view, so draining a chunk does not re-copy its tail.
        self._buffer = self._buffer[take:]
        return take

    def close(self) -> None:
        # Releases the connection back to the pool when a reader stops part way through
        # a body, which the caller's own `close` would otherwise wait for.
        self._response.close()
        super().close()


def response_text_stream(response: requests.Response, encoding: str = "utf-8") -> io.TextIOWrapper:
    """Read a streaming response body as a text file, for the ``csv`` module to parse.

    Keeps the line terminators csv needs for quoted multi-line values, which
    ``iter_lines`` strips, and decodes gzip on the way through.
    """
    return io.TextIOWrapper(
        io.BufferedReader(_ResponseByteStream(response, CHUNK_BYTES)), encoding=encoding, newline=""
    )
