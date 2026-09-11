import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import response_text_stream
from products.warehouse_sources.backend.temporal.data_imports.sources.common.tests.raw_stream import ClosingRawStream


def _response(body: bytes) -> requests.Response:
    response = requests.Response()
    response.raw = ClosingRawStream(body)
    response.status_code = 200
    return response


class TestResponseTextStream:
    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(b"a,b\n1,2\n", id="rows"),
            pytest.param(b"a,b\n", id="header with trailing newline"),
            pytest.param(b"a,b", id="header without trailing newline"),
            pytest.param(b"", id="no body at all"),
        ],
    )
    def test_reads_a_body_to_the_end_and_past_it(self, body: bytes) -> None:
        stream = response_text_stream(_response(body))

        assert stream.read() == body.decode()
        # A csv reader keeps asking for the next line after the body runs out. Reading the raw
        # stream directly raises ValueError here, because urllib3 closed it at EOF.
        assert stream.read() == ""

    def test_reassembles_a_body_that_spans_several_reads(self) -> None:
        body = b"a,b\n" + b"".join(b"%d,%d\n" % (index, index) for index in range(20_000))

        assert response_text_stream(_response(body)).read() == body.decode()

    def test_closing_part_way_through_releases_the_response(self) -> None:
        # A reader that stops early has to hand the connection back to the pool. Nothing else
        # closes the response, so a stream that keeps it open holds the connection until GC.
        response = _response(b"a,b\n1,2\n3,4\n")
        stream = response_text_stream(response)
        stream.readline()

        stream.close()

        assert response.raw.closed

    def test_keeps_the_newlines_inside_a_quoted_field(self) -> None:
        stream = response_text_stream(_response(b'a,b\n"line one\nline two",2\n'))

        assert stream.read() == 'a,b\n"line one\nline two",2\n'
