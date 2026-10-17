# Profile, its Fields and Rig work together through members QA shouldn't see in completions.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import difflib
from collections.abc import Sequence
from typing import Any, Generic, LiteralString, Never, NoReturn, TypeVar, cast, overload

from itch._errors import ItchError, ProfileError
from itch._rig import CHANNELS, Position, Rig

V = TypeVar("V", bound=LiteralString)


class Alias:
    """Another name for a Value of the same Field. Make one with `alias()`."""

    def __init__(self, target: str) -> None:
        self.target = target


def alias(value: str) -> Alias:
    """Another name for an existing Value, such as `"movie": alias("cinema")`."""
    return Alias(value)


Encodings = list[Position] | list[list[Position]] | Alias
"""What a Value is: one Encoding, a list of Encodings, or an alias."""


def field(channels: list[int], values: dict[V, Encodings]) -> Field[V]:
    """Declares a Field: the Channels it uses, and each Value's on/off positions.

    List one position per Channel, in `channels` order.
    """
    return Field(channels, values)


class Field(Generic[V]):
    """One named setting of a Profile, on a fixed set of Channels. Make one with `field()`."""

    def __init__(self, channels: list[int], values: dict[V, Encodings]) -> None:
        self._channels = channels
        self._values = values
        self.name = "?"
        self._where = "?"
        """The Profile and Field, such as `AcmeWidget.mode`, for messages."""
        self._mask = 0
        self._encodings: dict[str, list[int]] = {}
        """Each Value's Encodings as Channel bits, Encoding 1 first."""
        self._aliases: dict[str, str] = {}

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name
        self._where = f"{owner.__name__}.{name}"

    def _check(self) -> None:
        """Checks the Field as written and works out its bits. Raises `ProfileError`."""
        where = self._where
        # Checked as written, since a Profile may have type errors its author didn't see.
        channels, values = cast(object, self._channels), cast(object, self._values)
        if not isinstance(channels, list):
            example = channels if type(channels) is int else "1, 2"
            raise ProfileError(f"{where}: `channels` should be a list, e.g. channels=[{example}].")
        if not self._channels:
            raise ProfileError(
                f"{where}: `channels` is empty. List the Channels it uses, e.g. channels=[1, 2]."
            )
        for channel in self._channels:
            if type(channel) is not int or channel not in CHANNELS:
                raise ProfileError(
                    f"{where}: Channel {channel!r} doesn't exist. Channels are numbered 1 to 16."
                )
            if self._mask & 1 << (channel - 1):
                raise ProfileError(f"{where}: Channel {channel} is listed twice in `channels`.")
            self._mask |= 1 << (channel - 1)
        example = _show(["on"] * len(self._channels))
        if not isinstance(values, dict):
            raise ProfileError(
                f"{where}: `values` should be a dict of names and positions, "
                f'e.g. values={{"night": {example}}}.'
            )
        if not self._values:
            raise ProfileError(
                f"{where}: `values` is empty. Give each Value a name and its positions, "
                f'e.g. "night": {example}.'
            )
        seen: dict[int, tuple[str, str]] = {}
        """The Value and label of the Encoding already using each pattern of bits."""
        for value, spec in cast(dict[object, object], self._values).items():
            if not isinstance(value, str):
                raise ProfileError(
                    f'{where}: the Value name {value!r} needs quotes, like "{value}".'
                )
            if isinstance(spec, Alias):
                self._aliases[value] = spec.target
                continue
            encodings = self._split(value, spec, example)
            self._encodings[value] = []
            for number, positions in enumerate(encodings, 1):
                label = f'"{value}"' if len(encodings) == 1 else f'"{value}" Encoding {number}'
                self._encodings[value].append(self._check_encoding(value, label, positions, seen))
        for name, target in self._aliases.items():
            if target in self._aliases:
                final = self._aliases[target]
                if target != name and final in self._encodings:
                    instead = f'"{final}" instead'
                elif self._encodings:
                    instead = f'a Value, such as "{next(iter(self._encodings))}"'
                else:
                    instead = "a Value"
                points = "itself" if target == name else f'"{target}", which is itself an alias'
                raise ProfileError(
                    f'{where}: alias "{name}" points to {points}. Point it at {instead}.'
                )
            if target not in self._encodings:
                raise ProfileError(
                    f'{where}: alias "{name}" points to "{target}", but there is no such Value.'
                    + _did_you_mean(target, list(self._encodings))
                )

    def _split(self, value: str, spec: object, example: str) -> list[list[object]]:
        """A Value's Encodings, from one list of positions or a list of such lists."""
        if not isinstance(spec, list) or not spec:
            raise ProfileError(
                f'{self._where}: Value "{value}" should be a list of on/off, one per Channel, '
                f'e.g. "{value}": {example}. If it has several Encodings, put one such list per '
                "line inside another list."
            )
        items = cast(list[object], spec)
        if all(isinstance(item, list) for item in items):
            return cast(list[list[object]], items)
        if any(isinstance(item, list) for item in items):
            raise ProfileError(
                f'{self._where}: Value "{value}" mixes single positions and lists. Write either '
                f"one list like {example}, or a list of such lists (one per Encoding)."
            )
        return [items]

    def _check_encoding(
        self, value: str, label: str, positions: list[object], seen: dict[int, tuple[str, str]]
    ) -> int:
        """The bits of one Encoding, checked against the Field and the Encodings `seen` so far."""
        where = self._where
        n = len(self._channels)
        if len(positions) != n:
            channels = ", ".join(f"CH{channel}" for channel in self._channels)
            raise ProfileError(
                f"{where}: {label} has {_count(len(positions), 'position')}, but {self.name} uses "
                f"{_count(n, 'Channel')} ({channels}). Give one on/off per Channel, in that order."
            )
        bits = 0
        for channel, position in zip(self._channels, positions, strict=True):
            if position not in ("on", "off"):
                raise ProfileError(
                    f'{where}: {label} has "{position}" for CH{channel}. Use "on" or "off".'
                )
            if position == "on":
                bits |= 1 << (channel - 1)
        if (other := seen.get(bits)) is not None:
            other_value, other_label = other
            hint = (
                "Remove one of them."
                if other_value == value
                else f'If they are two names for the same setting, make "{value}" an alias of '
                f'"{other_value}".'
            )
            both = _show(self._positions(bits))
            raise ProfileError(f"{where}: {other_label} and {label} are both {both}. {hint}")
        seen[bits] = (value, label)
        return bits

    def _canonical(self, value: str) -> str:
        """The Value a name stands for, following an alias."""
        canonical = self._aliases.get(value, value)
        if canonical not in self._encodings:
            names = [*self._encodings, *self._aliases]
            choices = ", ".join(f'"{name}"' for name in names)
            raise ValueError(
                f'{self.name} has no Value "{value}".{_did_you_mean(value, names)} '
                f"Choose one of: {choices}."
            )
        return canonical

    def _encoding(self, value: str, number: int) -> int:
        """The bits of one Encoding of a Value."""
        encodings = self._encodings[self._canonical(value)]
        count = len(encodings)
        if type(number) is not int or not 1 <= number <= count:
            allowed = "1" if count == 1 else f"1 to {count}"
            raise ValueError(
                f'{self.name}: "{value}" has {_count(count, "Encoding")}, '
                f"so `encoding` must be {allowed}, not {number!r}."
            )
        return encodings[number - 1]

    def _decode(self, state: int) -> tuple[str, int]:
        """The Value and Encoding number the Channels in `state` are in."""
        bits = state & self._mask
        for value, encodings in self._encodings.items():
            if bits in encodings:
                return value, encodings.index(bits) + 1
        channels = ", ".join(f"CH{channel}" for channel in self._channels)
        raise ItchError(
            f"{channels} are {_show(self._positions(bits))}, "
            f"which isn't any Value of {self._where}."
        )

    def _positions(self, bits: int) -> list[Position]:
        return ["on" if bits >> (channel - 1) & 1 else "off" for channel in self._channels]

    @overload
    def __get__(self, dut: None, owner: type | None = None) -> Field[V]: ...
    @overload
    def __get__(self, dut: Profile, owner: type | None = None) -> FieldOnRig[V]: ...
    def __get__(self, dut: Profile | None, owner: type | None = None) -> Field[V] | FieldOnRig[V]:
        if dut is None:
            return self
        return FieldOnRig(self, dut)

    def __set__(self, dut: Profile, value: Never) -> NoReturn:
        # Without this, `dut.mode = "cinema"` would quietly hide the Field and change nothing.
        raise AttributeError(f'Use dut.{self.name}.set("{value}") to change {self.name}.')


class FieldOnRig(Generic[V]):
    """A Field of one DUT, ready to set or read on its Rig."""

    def __init__(self, field: Field[V], dut: Profile) -> None:
        self._field = field
        self._dut = dut

    def set(self, value: V, encoding: int = 1) -> None:
        """Sets a Value. A Value with several Encodings uses Encoding 1 unless you pick another.

        Needs a session.
        """
        self._dut._write(self._field, self._field._encoding(value, encoding))

    def get(self) -> V:
        """The Value the Channels are in now. An alias reads back as the Value it names."""
        return self.get_encoding().value

    def get_encoding(self) -> Encoding[V]:
        """The Value and which of its Encodings the Channels are in now."""
        value, number = self._field._decode(self._dut._rig._read_channels())
        return Encoding(self, cast(V, value), number)

    def encodings(self, value: V) -> list[Encoding[V]]:
        """Every Encoding of one Value, to set and test each in turn."""
        canonical = cast(V, self._field._canonical(value))
        count = len(self._field._encodings[canonical])
        return [Encoding(self, canonical, number) for number in range(1, count + 1)]

    def all_encodings(self) -> list[Encoding[V]]:
        """Every Encoding of every Value. Aliases aren't repeated."""
        return [e for value in self._field._encodings for e in self.encodings(cast(V, value))]

    def __repr__(self) -> str:
        return f"<Field {self._field._where}>"


class Encoding(Generic[V]):
    """One on/off pattern of a Value. `set()` writes exactly this pattern."""

    def __init__(self, field: FieldOnRig[V], value: V, number: int) -> None:
        self._field = field
        self.value: V = value
        """The Value, such as `"night"`."""
        self.number = number
        """Which of the Value's Encodings this is, counting from 1."""

    @property
    def positions(self) -> list[Position]:
        """The Field's Channels in this Encoding, in `channels` order."""
        field = self._field._field
        return field._positions(field._encodings[self.value][self.number - 1])

    def set(self) -> None:
        """Sets the Value using this Encoding. Needs a session."""
        self._field.set(self.value, encoding=self.number)

    def __repr__(self) -> str:
        field = self._field._field
        count = len(field._encodings[self.value])
        return (
            f'{field.name}="{self.value}" Encoding {self.number} of {count} {_show(self.positions)}'
        )


class Profile:
    """Base class of a DUT model's Profile. Subclass it and declare each Field with `field()`."""

    _fields: dict[str, Field[Any]]

    def __init_subclass__(cls) -> None:
        cls._fields = {k: v for k, v in vars(cls).items() if isinstance(v, Field)}
        for f in cls._fields.values():
            f._check()

    def __init__(self, rig: Rig) -> None:
        self._rig = rig

    def _write(self, field: Field[Any], bits: int) -> None:
        """Writes one Field's bits. Every Field write goes through here."""
        self._rig._write_channels(field._mask, bits)


def _show(positions: Sequence[str]) -> str:
    """Positions the way a Profile lists them: `["on", "off"]`."""
    return "[" + ", ".join(f'"{position}"' for position in positions) + "]"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _did_you_mean(name: object, names: list[str]) -> str:
    close = difflib.get_close_matches(str(name), names, n=1)
    return f' Did you mean "{close[0]}"?' if close else ""
