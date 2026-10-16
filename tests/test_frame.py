from typing import Any

from itch._frame import FrameDecoder, encode_frame


def test_frames_match_vectors(vectors: dict[str, Any]) -> None:
    for case in vectors["frames"]:
        payload, frame = bytes.fromhex(case["payload"]), bytes.fromhex(case["frame"])
        assert encode_frame(payload) == frame, case["name"]
        assert FrameDecoder().feed(frame) == [payload], case["name"]


def test_streams_match_vectors(vectors: dict[str, Any]) -> None:
    for case in vectors["streams"]:
        decoder = FrameDecoder()
        payloads = decoder.feed(bytes.fromhex(case["stream"]))
        assert payloads == [bytes.fromhex(p) for p in case["payloads"]], case["name"]
        assert decoder.crc_failures == case["crc_failures"], case["name"]
        assert decoder.oversized_frames == case["oversized_frames"], case["name"]


def test_a_stream_split_anywhere_gives_the_same_payloads(vectors: dict[str, Any]) -> None:
    for case in vectors["streams"]:
        decoder = FrameDecoder()
        payloads = [
            p for byte in bytes.fromhex(case["stream"]) for p in decoder.feed(bytes([byte]))
        ]
        assert payloads == [bytes.fromhex(p) for p in case["payloads"]], case["name"]
