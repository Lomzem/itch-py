"""The private wire codec against the conformance vectors, plus strict decoding."""

from typing import Any, get_type_hints

import pytest

from itch._wire import (
    DecodeError,
    ErrorCode,
    ErrorResponse,
    Hello,
    HelloReply,
    Message,
    OkResponse,
    Request,
    RequestType,
    decode,
    encode,
)

REQUESTS: dict[str, type[Any]] = {"Hello": Hello}
REPLIES: dict[str, type[Any]] = {"Hello": HelloReply}


def body(cls: type[Any], fields: dict[str, Any]) -> Any:
    """Builds a message body from its vector fields, named as in the byte tables."""
    hints = get_type_hints(cls)
    for name, value in fields.items():
        if hints[name] is bytes:
            fields[name] = bytes.fromhex(value)
        elif hints[name] is int and isinstance(value, str):
            fields[name] = int(value, 16)
    return cls(**fields)


def message(case: dict[str, Any]) -> Message:
    fields = dict(case)
    kind, type_ = fields.pop("kind"), fields.pop("type")
    request_id = fields.pop("request_id")
    if kind == "request":
        return Request(request_id, body(REQUESTS[type_], fields))
    status = fields.pop("status")
    if status == "Ok":
        return OkResponse(request_id, body(REPLIES[type_], fields))
    return ErrorResponse(RequestType[type_], request_id, ErrorCode[status], fields["detail"])


def test_messages_match_vectors(vectors: dict[str, Any]) -> None:
    for case in vectors["messages"]:
        expected, payload = message(case["message"]), bytes.fromhex(case["payload"])
        assert encode(expected) == payload, case["name"]
        assert decode(payload) == expected, case["name"]


def test_every_message_type_has_a_vector(vectors: dict[str, Any]) -> None:
    covered = {case["message"]["type"] for case in vectors["messages"]}
    assert covered == {t.name for t in RequestType}


# The Hello reply from messages.md, one field per entry.
HELLO_OK = {
    "header": "81 78 56 34 12 00",
    "protocol": "01 00",
    "firmware_version": "05 31 2e 30 2e 30",
    "dirty": "00",
    "features": "00",
    "channel_count": "10",
    "board_revision": "01 41",
    "hardware_id": "60 55 f9 c0 27 18",
    "label": "0b 69 74 63 68 2d 43 30 32 37 31 38",
}


def hello_ok(**fields: str) -> bytes:
    return bytes.fromhex(" ".join({**HELLO_OK, **fields}.values()))


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(hello_ok()[:-1], id="short body"),
        pytest.param(hello_ok() + b"\x00", id="trailing byte"),
        pytest.param(hello_ok(dirty="02"), id="bool not 0 or 1"),
        pytest.param(hello_ok(label="02 c3 28"), id="invalid UTF-8"),
        pytest.param(hello_ok(label="41" + " 61" * 65), id="label over 64 bytes"),
        pytest.param(hello_ok(label="0c 69 74 63 68"), id="text longer than the body"),
        pytest.param(bytes.fromhex("01 78 56 34"), id="request under 5 bytes"),
        pytest.param(bytes.fromhex("01 78 56 34 12 00"), id="request with trailing byte"),
        pytest.param(bytes.fromhex("3f 78 56 34 12"), id="unknown request type"),
        pytest.param(bytes.fromhex("bf 78 56 34 12 00"), id="ok reply to an unknown type"),
        pytest.param(b"", id="empty"),
    ],
)
def test_rejects_malformed_payloads(payload: bytes) -> None:
    with pytest.raises(DecodeError):
        decode(payload)


def test_error_response_keeps_an_unknown_code() -> None:
    reply = decode(bytes.fromhex("81 78 56 34 12 63 00"))
    assert reply == ErrorResponse(RequestType.Hello, 0x12345678, 99, "")
