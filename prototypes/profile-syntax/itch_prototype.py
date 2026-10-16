"""PROTOTYPE, throwaway. A fake `itch` library for judging Profile syntax.

Not the real itch-py: no USB, no protocol. The Rig is an in-memory fake that
prints its Channels after every change. See README.md.
"""

from __future__ import annotations

import difflib
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Any, Generic, Literal, LiteralString, TypeVar, cast, overload

V = TypeVar("V", bound=LiteralString)
Position = Literal["on", "off"]


def _show(positions: Sequence[str]) -> str:
    """Format positions the way QA writes them: ["on", "off"]."""
    return "[" + ", ".join(f'"{p}"' for p in positions) + "]"


class ProfileError(Exception):
    """A Profile is written wrongly. Raised when the Profile is loaded."""


class LeaseRequiredError(Exception):
    pass


# --- Rig (fake) -------------------------------------------------------------


def _check_channel(channel: int) -> None:
    if isinstance(channel, bool) or not isinstance(channel, int) or not 1 <= channel <= 16:
        raise ValueError(f"Channel {channel!r} doesn't exist. Channels are numbered 1 to 16.")


class Rig:
    def __init__(self, name: str) -> None:
        self.name = name
        self._state = 0  # bit 0 = CH1 ... bit 15 = CH16
        self._in_session = False

    @classmethod
    def connect(cls, name: str | None = None) -> Rig:
        rig = cls(name or "itch-C02718")
        print(f"[fake rig] connected to {rig.name}, all Channels off")
        return rig

    @contextmanager
    def session(self) -> Generator[None]:
        self._in_session = True
        print("[fake rig] Lease acquired")
        try:
            yield
        finally:
            self._in_session = False
            print("[fake rig] Lease released")

    def set_channel(self, channel: int, position: Position) -> None:
        _check_channel(channel)
        if position not in ("on", "off"):
            raise ValueError(f'Position {position!r} isn\'t valid. Use "on" or "off".')
        bit = 1 << (channel - 1)
        self._write(bit, bit if position == "on" else 0)

    def clear(self) -> None:
        self._write(0xFFFF, 0)

    # Reading doesn't need the Lease.
    def get_channel(self, channel: int) -> Position:
        """The position of one Channel, e.g. rig.get_channel(3) -> "on"."""
        _check_channel(channel)
        return "on" if self._read() >> (channel - 1) & 1 else "off"

    def get_channels(self, channels: list[int] | None = None) -> dict[int, Position]:
        """Positions of the given Channels, or all 16, e.g. {1: "on", 2: "off"}."""
        if channels is None:
            channels = list(range(1, 17))
        return {ch: self.get_channel(ch) for ch in channels}

    # Mask write: the one write primitive on the wire.
    def _write(self, mask: int, values: int) -> None:
        if not self._in_session:
            raise LeaseRequiredError(
                "Changing Channels needs the Lease. Wrap your changes in `with rig.session():`."
            )
        self._state = (self._state & ~mask) | (values & mask)
        on = [f"CH{i + 1}" for i in range(16) if self._state >> i & 1]
        print(f"[fake rig] Channels on: {', '.join(on) or 'none'}")

    def _read(self) -> int:
        return self._state


# --- Profiles ----------------------------------------------------------------


class BatchConflictError(Exception):
    """Two Fields in one batch need different positions on a shared Channel."""


class Alias:
    def __init__(self, target: str) -> None:
        self.target = target


def alias(value: str) -> Alias:
    """Another name for an existing Value, e.g. "movie": alias("cinema")."""
    return Alias(value)


# What a Value can be: one Encoding, a list of Encodings, or an alias.
Spec = list[Position] | list[list[Position]] | Alias


class Field(Generic[V]):
    """One named setting of a Profile, on a fixed set of Channels."""

    def __init__(self, channels: list[int], values: dict[V, Spec]) -> None:
        self.channels = channels
        self.raw_values = values
        self.name = "?"
        self.encodings: dict[str, list[int]] = {}  # Value -> bits of each Encoding; the first is the default
        self.aliases: dict[str, str] = {}  # alias -> Value
        self.mask = 0

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    # Called from Profile.__init_subclass__ so messages can name the Profile.
    def _check(self, profile: str) -> None:
        where = f"{profile}.{self.name}"
        if not self.channels:
            raise ProfileError(f"{where}: `channels` is empty. List the Channels it uses, e.g. channels=[1, 2].")
        for ch in self.channels:
            if not isinstance(ch, int) or not 1 <= ch <= 16:
                raise ProfileError(f"{where}: Channel {ch!r} doesn't exist. Channels are numbered 1 to 16.")
            if self.channels.count(ch) > 1:
                raise ProfileError(f"{where}: Channel {ch} is listed twice in `channels`.")
            self.mask |= 1 << (ch - 1)
        n = len(self.channels)
        chs = ", ".join(f"CH{c}" for c in self.channels)
        if not self.raw_values:
            raise ProfileError(f'{where}: `values` is empty. Give each Value a name, e.g. "1080p": ["off", "on"].')
        example = _show(["on"] * n)
        seen: dict[int, str] = {}  # bits -> which Value/Encoding already uses them
        for value, spec in self.raw_values.items():
            if isinstance(spec, Alias):
                self.aliases[value] = spec.target
                continue
            if not isinstance(spec, list) or not spec:
                raise ProfileError(
                    f'{where}: Value "{value}" should be a list of on/off, one per Channel, e.g. "{value}": {example}. '
                    f"If it has several Encodings, put one such list per line inside another list."
                )
            encodings: list[list[str]]
            if all(isinstance(p, str) for p in spec):
                encodings = [cast(list[str], spec)]
            elif all(isinstance(p, list) for p in spec):
                encodings = cast(list[list[str]], spec)
            else:
                raise ProfileError(
                    f'{where}: Value "{value}" mixes single positions and lists. Write either one list like {example}, '
                    f"or a list of such lists (one per Encoding)."
                )
            bits_list: list[int] = []
            for number, positions in enumerate(encodings, 1):
                label = f'"{value}"' if len(encodings) == 1 else f'"{value}" Encoding {number}'
                if len(positions) != n:
                    raise ProfileError(
                        f"{where}: {label} has {len(positions)} position{'s' if len(positions) != 1 else ''}, "
                        f"but {self.name} uses {n} Channel{'s' if n != 1 else ''} ({chs}). "
                        "Give one on/off per Channel, in that order."
                    )
                bits = 0
                for ch, pos in zip(self.channels, positions):
                    if pos not in ("on", "off"):
                        raise ProfileError(f'{where}: {label} has "{pos}" for CH{ch}. Use "on" or "off".')
                    if pos == "on":
                        bits |= 1 << (ch - 1)
                if bits in seen:
                    other = seen[bits]
                    hint = (
                        "Remove one of them."
                        if other.startswith(f'"{value}"')
                        else f'If they are two names for the same setting, make "{value}" an alias of {other.split(" ")[0]}.'
                    )
                    raise ProfileError(f"{where}: {other} and {label} are both {_show(positions)}. {hint}")
                seen[bits] = label
                bits_list.append(bits)
            self.encodings[value] = bits_list
        for name, target in self.aliases.items():
            if target in self.aliases:
                raise ProfileError(
                    f'{where}: alias "{name}" points to "{target}", which is itself an alias. '
                    f'Point it at "{self.aliases[target]}" instead.'
                )
            if target not in self.encodings:
                raise ProfileError(f'{where}: alias "{name}" points to "{target}", but there is no such Value.{self._hint(target)}')

    def _hint(self, value: str) -> str:
        close = difflib.get_close_matches(value, [*self.encodings, *self.aliases], n=1)
        return f' Did you mean "{close[0]}"?' if close else ""

    def _canonical(self, value: str) -> str:
        """The Value a name stands for (follows aliases)."""
        value = self.aliases.get(value, value)
        if value not in self.encodings:
            choices = ", ".join(f'"{v}"' for v in [*self.encodings, *self.aliases])
            raise ValueError(f'{self.name} has no Value "{value}".{self._hint(value)} Choose one of: {choices}.')
        return value

    def _bits_for(self, value: str, encoding: int) -> int:
        bits_list = self.encodings[self._canonical(value)]
        if not 1 <= encoding <= len(bits_list):
            count = len(bits_list)
            raise ValueError(
                f'{self.name}: "{value}" has {count} Encoding{"s" if count != 1 else ""}, '
                f"so `encoding` must be {'1' if count == 1 else f'1 to {count}'}, not {encoding}."
            )
        return bits_list[encoding - 1]

    def _decode(self, state: int) -> tuple[str, int]:
        """Which Value and Encoding the Channels are in."""
        bits = state & self.mask
        for value, bits_list in self.encodings.items():
            if bits in bits_list:
                return value, bits_list.index(bits) + 1
        raise ProfileError(f"{self.name}: the Channels are {_show(self._positions(bits))}, which isn't any Value in the Profile.")

    def _positions(self, bits: int) -> list[str]:
        return ["on" if bits >> (c - 1) & 1 else "off" for c in self.channels]

    # `dut.mode` gives a FieldOnRig with .set()/.get(). Assignment
    # (`dut.mode = "cinema"`) was measured to get no Value autocomplete.
    @overload
    def __get__(self, obj: None, owner: type | None = None) -> Field[V]: ...
    @overload
    def __get__(self, obj: Profile, owner: type | None = None) -> FieldOnRig[V]: ...
    def __get__(self, obj: Profile | None, owner: type | None = None) -> Any:
        if obj is None:
            return self
        return FieldOnRig(self, obj)


class Encoding(Generic[V]):
    """One on/off pattern of a Value. `set()` writes exactly this pattern."""

    def __init__(self, on_rig: FieldOnRig[V], value: V, number: int) -> None:
        self._on_rig = on_rig
        self.value = value
        self.number = number
        f = on_rig._field
        self.count = len(f.encodings[value])
        self.positions = f._positions(f.encodings[value][number - 1])

    def set(self) -> None:
        self._on_rig.set(self.value, encoding=self.number)

    def __repr__(self) -> str:
        return f'{self._on_rig._field.name}="{self.value}" Encoding {self.number} of {self.count} {_show(self.positions)}'


class FieldOnRig(Generic[V]):
    """A Field of one DUT's Profile, ready to set or read on the Rig."""

    def __init__(self, f: Field[V], dut: Profile) -> None:
        self._field = f
        self._dut = dut

    def set(self, value: V, encoding: int = 1) -> None:
        """Set a Value. Values with several Encodings use Encoding 1 unless you pick another."""
        bits = self._field._bits_for(value, encoding)
        label = f'{self._field.name}="{value}"'
        if self._dut._pending is not None:
            self._dut._pending[self._field.name] = (label, self._field.mask, bits)
        else:
            self._dut._rig._write(self._field.mask, bits)

    def get(self) -> V:
        """The Value the Channels are in now. Aliases read back as the Value they stand for."""
        return cast(V, self._field._decode(self._dut._rig._read())[0])

    def get_encoding(self) -> Encoding[V]:
        """The Value and which of its Encodings the Channels are in now."""
        value, number = self._field._decode(self._dut._rig._read())
        return Encoding(self, cast(V, value), number)

    def encodings(self, value: V) -> list[Encoding[V]]:
        """Every Encoding of one Value, to test each in turn."""
        canonical = self._field._canonical(value)
        return [Encoding(self, cast(V, canonical), i) for i in range(1, len(self._field.encodings[canonical]) + 1)]

    def all_encodings(self) -> list[Encoding[V]]:
        """Every Encoding of every Value (aliases aren't repeated)."""
        return [enc for value in self._field.encodings for enc in self.encodings(cast(V, value))]

    def __repr__(self) -> str:
        return f"<{self._field.name}>"


def field(channels: list[int], values: dict[V, Spec]) -> Field[V]:
    """Declare a Field: the Channels it uses, and each Value's on/off positions."""
    return Field(channels, values)


class Profile:
    """Base class for a DUT model's Profile."""

    _fields: dict[str, Field[Any]]

    def __init_subclass__(cls) -> None:
        # Fields may share Channels (one switch with two meanings, or a switch
        # that is part of a bigger setting); batch() catches contradictions.
        cls._fields = {k: v for k, v in vars(cls).items() if isinstance(v, Field)}
        for f in cls._fields.values():
            f._check(cls.__name__)

    def __init__(self, rig: Rig) -> None:
        self._rig = rig
        self._pending: dict[str, tuple[str, int, int]] | None = None  # Field -> (label, mask, bits)

    @contextmanager
    def batch(self) -> Generator[None]:
        """Change several Fields in one write. Setting the same Field twice keeps the last."""
        self._pending = {}
        try:
            yield
            pending = list(self._pending.values())
        finally:
            self._pending = None
        mask = values = 0
        for label, m, v in pending:
            clash = mask & m & (values ^ v)
            if clash:
                ch = (clash & -clash).bit_length()
                other = next(lb for lb, om, ov in pending if om & clash and (ov ^ v) & clash)
                raise BatchConflictError(
                    f"CH{ch}: {other} needs {'on' if not v & clash else 'off'}, but {label} needs "
                    f"{'on' if v & clash else 'off'}. Set only one of them in a batch, or pick Values that agree. "
                    "No Channels were changed."
                )
            mask |= m
            values = (values & ~m) | v
        self._rig._write(mask, values)

    def __repr__(self) -> str:
        state = self._rig._read()
        parts = []
        for name, f in self._fields.items():
            try:
                value, number = f._decode(state)
                many = len(f.encodings[value]) > 1
                parts.append(f"{name}={value!r}" + (f" (Encoding {number})" if many else ""))
            except ProfileError:
                parts.append(f"{name}=<unknown>")
        return f"{type(self).__name__}({', '.join(parts)})"
