"""Opting in to the Rig's logs through Python `logging`."""

import logging
import threading

import pytest
from scripted_rig import ACME_HELLO, ScriptedRig, answering
from tcp_client import other_client

from itch import Rig
from itch._connection import Connection
from itch._transport import open_tcp
from itch._wire import (
    Hello,
    HelloReply,
    Lock,
    LockReply,
    LogEvent,
    Message,
    OkResponse,
    ReleaseLock,
    ReleaseLockReply,
    Request,
    SetLogLevel,
    SetLogLevelReply,
)


def test_turns_rig_logs_off_right_after_hello_then_locks() -> None:
    with answering(ACME_HELLO) as peer, Rig.connect(peer.url, holder="qa@bench-pc"):
        assert [request.body for request in peer.requests] == [
            Hello(),
            SetLogLevel(0),
            Lock("qa@bench-pc", takeover=False),
        ]


@pytest.mark.parametrize(
    ("python_level", "rig_level"),
    [
        (logging.DEBUG, 4),
        (logging.INFO, 3),
        (logging.WARNING, 2),
        (logging.ERROR, 1),
        (logging.CRITICAL, 1),
    ],
)
def test_sets_the_rig_log_level_the_user_opted_in_to(python_level: int, rig_level: int) -> None:
    with answering(ACME_HELLO) as peer, Rig.connect(peer.url, log_level=python_level):
        assert peer.requests[1].body == SetLogLevel(rig_level)


def test_forwards_rig_logs_to_python_logging(sim: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="itch.rig")
    with Rig.connect(sim, log_level=logging.INFO) as rig:
        other_client(sim).close()
        rig.get_channels()  # Its reply comes after the Log Events, which go first.
    record = next(r for r in caplog.records if "connected" in r.message)
    assert record.name == "itch.rig"
    assert record.levelno == logging.INFO
    assert record.message.startswith(f"Rig {rig.label}: "), record.message


def test_forwards_rig_logs_while_the_script_is_idle(
    sim: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="itch.rig")

    class Waiting(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.heard = threading.Event()

        def emit(self, record: logging.LogRecord) -> None:
            if "connected" in record.getMessage():
                self.heard.set()

    logger = logging.getLogger("itch.rig")
    handler = Waiting()
    logger.addHandler(handler)
    try:
        with Rig.connect(sim, log_level=logging.INFO):
            other_client(sim).close()  # The sim logs this connection to every opted-in one.
            assert handler.heard.wait(1.0)
    finally:
        logger.removeHandler(handler)


def test_forwards_rig_logs_still_unread_when_the_rig_closes(
    sim: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="itch.rig")
    with Rig.connect(sim, log_level=logging.INFO):
        other_client(sim).close()
    assert any("connected" in r.message for r in caplog.records), caplog.records


def test_forwards_nothing_by_default(sim: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="itch.rig")
    with Rig.connect(sim) as rig:
        other_client(sim).close()
        rig.get_channels()
    assert caplog.records == []


def test_reports_dropped_rig_logs_and_ignores_logs_from_before_the_level_is_set(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="itch.rig")
    # The peer sends this Log Event ahead of every reply, including Hello's and SetLogLevel's.
    with (
        answering(ACME_HELLO, LogEvent(level=2, dropped=3, text="expander fault")) as peer,
        Connection.open(open_tcp(peer.url), log_level=logging.DEBUG) as connection,
    ):
        connection.request(Hello(), HelloReply)
    assert [(r.levelno, r.message) for r in caplog.records] == [
        (logging.WARNING, "Rig bench3 dropped 3 log messages"),
        (logging.WARNING, "Rig bench3: expander fault"),
    ]


def test_forwards_nothing_below_the_level_the_user_opted_in_to(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="itch.rig")
    # The Rig has no level above error, so it sends errors to a client that wants critical.
    with (
        answering(ACME_HELLO, LogEvent(level=1, dropped=3, text="expander gone")) as peer,
        Connection.open(open_tcp(peer.url), log_level=logging.CRITICAL) as connection,
    ):
        connection.request(Hello(), HelloReply)
    assert caplog.records == []


def test_closing_twice_with_rig_logs_on_is_safe(sim: str) -> None:
    rig = Rig.connect(sim, log_level=logging.DEBUG)
    rig.close()
    rig.close()


def test_a_log_handler_may_use_the_rig(sim: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="itch.rig")

    class Reading(logging.Handler):
        def __init__(self, rig: Rig) -> None:
            super().__init__()
            self.rig = rig
            self.read: list[object] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.read.append(self.rig.get_channels([1]))

    logger = logging.getLogger("itch.rig")
    with Rig.connect(sim, log_level=logging.INFO) as rig:
        handler = Reading(rig)
        logger.addHandler(handler)
        try:
            other_client(sim).close()
            rig.get_channels()
        finally:
            logger.removeHandler(handler)
    assert handler.read


def test_a_log_handler_may_lock_the_rig_while_it_closes(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="itch.rig")

    def log_each_release(request: Request) -> list[Message]:
        match request.body:
            case Hello():
                return [OkResponse(request.request_id, ACME_HELLO)]
            case SetLogLevel():
                return [OkResponse(request.request_id, SetLogLevelReply())]
            case Lock():
                return [OkResponse(request.request_id, LockReply())]
            case _:
                event = LogEvent(level=3, dropped=0, text="released")
                return [event, OkResponse(request.request_id, ReleaseLockReply())]

    class Locking(logging.Handler):
        def __init__(self, rig: Rig) -> None:
            super().__init__()
            self.rig = rig
            self.locked = False

        def emit(self, record: logging.LogRecord) -> None:
            if not self.locked:
                self.locked = True
                with self.rig.lock():  # Waits for close() to finish releasing.
                    pass

    logger = logging.getLogger("itch.rig")
    with ScriptedRig(log_each_release) as peer:
        rig = Rig.connect(peer.url, holder="alice", log_level=logging.INFO)
        handler = Locking(rig)
        logger.addHandler(handler)
        try:
            closing = threading.Thread(target=rig.close, daemon=True)
            closing.start()
            closing.join(5)
            assert not closing.is_alive(), "close() deadlocked with the log handler"
        finally:
            logger.removeHandler(handler)
    assert handler.locked
    locks = [r.body for r in peer.requests if isinstance(r.body, Lock | ReleaseLock)]
    assert locks == [Lock("alice", False), ReleaseLock("alice")] * 2
