"""Removed API names fail at access, with actionable replacements and no Rig requests."""

import re
import traceback
from collections.abc import Callable
from typing import cast

import pytest
from acme_widget import AcmeWidget
from scripted_rig import after_connecting, granting_writes

from itch import Profile, Rig, field
from itch._wire import GetChannelsReply, OkResponse


@pytest.mark.parametrize(
    ("profiled", "name", "replacements"),
    [
        pytest.param(profiled, name, replacements, id=f"{owner}-{name}")
        for profiled, owner in [(False, "Rig"), (True, "AcmeWidget")]
        for name, replacements in [
            ("set_channel", (r"set\(", r"clear\(", r"write\(")),
            ("set_channels", (r"set\(", r"clear\(", r"write\(")),
            ("get_channel", (r"get\(channel\)",)),
            ("get_channels", (r"get_all\(\)",)),
            ("close", (r"disconnect\(\)",)),
        ]
    ]
    + [pytest.param(True, "batch", (r"dut\.apply\(",), id="AcmeWidget-batch")],
)
def test_removed_methods_name_their_replacements_and_stay_off_the_public_surface(
    profiled: bool, name: str, replacements: tuple[str, ...]
) -> None:
    with granting_writes() as peer:
        client = Rig.connect(peer.url, AcmeWidget) if profiled else Rig.connect(peer.url)
        with client:
            connected_requests = peer.requests.copy()
            with pytest.raises(AttributeError) as raised:
                getattr(client, name)
            message = str(raised.value)
            owner = "AcmeWidget" if profiled else "Rig"
            assert message.startswith(f"{owner}.{name}() was removed in itch-py 0.3.0.")
            for replacement in replacements:
                assert re.search(replacement, message), message
            assert "Did you mean" not in "".join(traceback.format_exception_only(raised.value))
            assert not hasattr(client, name)
            assert name not in dir(client)
            assert peer.requests == connected_requests


def test_former_method_names_are_usable_fields(sim: str) -> None:
    class AcmeWidget(Profile):
        batch = field(channels=[1], values={"disabled": [0], "enabled": [1]})
        close = field(channels=[2], values={"disabled": [0], "enabled": [1]})
        set_channels = field(channels=[3], values={"disabled": [0], "enabled": [1]})

    with Rig.connect(sim, AcmeWidget) as dut:
        dut.clear_all()
        dut.set(16)
        dut.apply(batch="enabled", set_channels="enabled")
        dut.close.set("enabled")
        assert dut.get_all() == 0x8007
        assert dut.batch.get() == "enabled"
        assert dut.close.get() == "enabled"
        assert dut.set_channels.get() == "enabled"
        dut.apply(batch="disabled", set_channels="disabled")
        dut.close.set("disabled")
        assert dut.get_all() == 0x8000
        assert dut.batch.get() == "disabled"
        assert dut.close.get() == "disabled"
        assert dut.set_channels.get() == "disabled"


@pytest.mark.parametrize("with_rig", [True, False], ids=["with-rig", "no-arguments"])
def test_public_profile_construction_points_to_connect_and_leaves_the_rig_usable(
    with_rig: bool,
) -> None:
    with (
        after_connecting(
            lambda request: [OkResponse(request.request_id, GetChannelsReply(0x8011))]
        ) as peer,
        Rig.connect(peer.url) as rig,
    ):
        connected_requests = peer.requests.copy()
        construct = cast(Callable[..., AcmeWidget], AcmeWidget)
        with pytest.raises(TypeError) as raised:
            construct(rig) if with_rig else construct()
        message = str(raised.value)
        assert "AcmeWidget(rig)" in message
        assert re.search(r'Rig\.connect\(".*", AcmeWidget\)', message), message
        assert peer.requests == connected_requests
        assert rig.get_all() == 0x8011
