"""The private wire codec against the conformance vectors, plus strict decoding."""

from typing import Any, get_type_hints

import pytest

from itch._wire import (
    AcquireLease,
    AcquireLeaseReply,
    Clear,
    ClearReply,
    DecodeError,
    ErrorCode,
    ErrorResponse,
    GetChannels,
    GetChannelsReply,
    GetStatus,
    GetStatusReply,
    Hello,
    HelloReply,
    Message,
    OkResponse,
    ReleaseLease,
    ReleaseLeaseReply,
    RenewLease,
    RenewLeaseReply,
    Request,
    RequestType,
    WriteChannels,
    WriteChannelsReply,
    decode,
    encode,
)

REQUESTS: dict[str, type[Any]] = {
    "Hello": Hello,
    "GetChannels": GetChannels,
    "WriteChannels": WriteChannels,
    "Clear": Clear,
    "GetStatus": GetStatus,
    "AcquireLease": AcquireLease,
    "RenewLease": RenewLease,
    "ReleaseLease": ReleaseLease,
}
REPLIES: dict[str, type[Any]] = {
    "Hello": HelloReply,
    "GetChannels": GetChannelsReply,
    "WriteChannels": WriteChannelsReply,
    "Clear": ClearReply,
    "GetStatus": GetStatusReply,
    "AcquireLease": AcquireLeaseReply,
    "RenewLease": RenewLeaseReply,
    "ReleaseLease": ReleaseLeaseReply,
}


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


def test_rejects_malformed_vectors(vectors: dict[str, Any]) -> None:
    known = {t.value for t in RequestType}
    for case in vectors["malformed"]:
        payload = bytes.fromhex(case["payload"])
        with pytest.raises(DecodeError):
            decode(payload)
        unknown_request = len(payload) >= 5 and payload[0] < 0x40 and payload[0] not in known
        assert (case["error"] == "UnknownRequest") == unknown_request, case["name"]


def test_error_response_keeps_an_unknown_code() -> None:
    reply = decode(bytes.fromhex("81 78 56 34 12 63 00"))
    assert reply == ErrorResponse(RequestType.Hello, 0x12345678, 99, "")
