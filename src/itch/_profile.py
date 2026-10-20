# Profile, its Fields and Rig work together through members QA shouldn't see in completions.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import ast
import difflib
import inspect
import textwrap
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Any, Generic, LiteralString, Never, NoReturn, TypeVar, cast, overload

from itch._errors import BatchConflictError, ItchError, ProfileError
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
        self._encodings: dict[str, tuple[int, ...]] = {}
        """Each Value's Encodings as Channel bits, Encoding 1 first. Set by `_check()`."""
        self._aliases: dict[str, str] = {}
        """The Value each alias names. Set by `_check()`."""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name
        self._where = f"{owner.__name__}.{name}"

    def _check(self) -> None:
        """Checks the Field as written and works out its bits, once. Raises `ProfileError`."""
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
        mask = 0
        for channel in self._channels:
            if type(channel) is not int or channel not in CHANNELS:
                raise ProfileError(
                    f"{where}: Channel {channel!r} doesn't exist. Channels are numbered 1 to 16."
                )
            if mask & 1 << (channel - 1):
                raise ProfileError(f"{where}: Channel {channel} is listed twice in `channels`.")
            mask |= 1 << (channel - 1)
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
        encodings: dict[str, tuple[int, ...]] = {}
        aliases: dict[str, str] = {}
        for value, spec in cast(dict[object, object], self._values).items():
            if not isinstance(value, str):
                raise ProfileError(
                    f'{where}: the Value name {value!r} needs quotes, like "{value}".'
                )
            if isinstance(spec, Alias):
                aliases[value] = spec.target
                continue
            split = self._split(value, spec, example)
            encodings[value] = tuple(
                self._check_encoding(
                    value,
                    f'"{value}"' if len(split) == 1 else f'"{value}" Encoding {number}',
                    positions,
                    seen,
                )
                for number, positions in enumerate(split, 1)
            )
        for name, target in aliases.items():
            if target in aliases:
                final = aliases[target]
                if target != name and final in encodings:
                    instead = f'"{final}" instead'
                elif encodings:
                    instead = f'a Value, such as "{next(iter(encodings))}"'
                else:
                    instead = "a Value"
                points = "itself" if target == name else f'"{target}", which is itself an alias'
                raise ProfileError(
                    f'{where}: alias "{name}" points to {points}. Point it at {instead}.'
                )
            if target not in encodings:
                raise ProfileError(
                    f'{where}: alias "{name}" points to "{target}", but there is no such Value.'
                    + _did_you_mean(target, list(encodings))
                )
        self._mask, self._encodings, self._aliases = mask, encodings, aliases

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

    def _select(self, value: str, number: int) -> _Selection:
        """One Encoding of the Value a name stands for. Raises `ValueError` for a bad pick."""
        selections = self._selections(value)
        count = len(selections)
        if type(number) is not int or not 1 <= number <= count:
            allowed = "1" if count == 1 else f"1 to {count}"
            raise ValueError(
                f'{self.name}: "{value}" has {_count(count, "Encoding")}, '
                f"so `encoding` must be {allowed}, not {number!r}."
            )
        return selections[number - 1]

    def _selections(self, value: str) -> list[_Selection]:
        """Every Encoding of the Value a name stands for, Encoding 1 first."""
        canonical = self._canonical(value)
        encodings = self._encodings[canonical]
        return [
            _Selection(self, canonical, number, len(encodings), bits)
            for number, bits in enumerate(encodings, 1)
        ]

    def _value_names(self) -> list[str]:
        """Every Value, without the aliases."""
        return list(self._encodings)

    def _decode(self, state: int) -> _Selection:
        """The Encoding the Channels in `state` are in."""
        if (found := self._find(state)) is not None:
            return found
        channels = ", ".join(f"CH{channel}" for channel in self._channels)
        raise ItchError(
            f"{channels} are {_show(self._positions(state & self._mask))}, "
            f"which isn't any Value of {self._where}."
        )

    def _find(self, state: int) -> _Selection | None:
        bits = state & self._mask
        for value, encodings in self._encodings.items():
            if bits in encodings:
                return _Selection(self, value, encodings.index(bits) + 1, len(encodings), bits)
        return None

    def _show(self, state: int) -> str:
        """The Field's Value in `state`, such as `mode="night" (Encoding 2)`."""
        if (found := self._find(state)) is None:
            return f"{self.name}={_show(self._positions(state & self._mask))} (no Value)"
        return found.label + (f" (Encoding {found.number})" if found.count > 1 else "")

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
        self._dut._write(self._field._select(value, encoding))

    def get(self) -> V:
        """The Value the Channels are in now. An alias reads back as the Value it names."""
        return self.get_encoding().value

    def get_encoding(self) -> Encoding[V]:
        """The Value and which of its Encodings the Channels are in now."""
        return Encoding(self._dut, self._field._decode(self._dut._rig._read_channels()))

    def encodings(self, value: V) -> list[Encoding[V]]:
        """Every Encoding of one Value, to set and test each in turn."""
        return [Encoding(self._dut, selection) for selection in self._field._selections(value)]

    def all_encodings(self) -> list[Encoding[V]]:
        """Every Encoding of every Value. Aliases aren't repeated."""
        return [e for value in self._field._value_names() for e in self.encodings(cast(V, value))]

    def __repr__(self) -> str:
        return f"<Field {self._field._where}>"


class Encoding(Generic[V]):
    """One on/off pattern of a Value. `set()` writes exactly this pattern."""

    def __init__(self, dut: Profile, selection: _Selection) -> None:
        self._dut = dut
        self._selection = selection

    @property
    def value(self) -> V:
        """The Value, such as `"night"`."""
        return cast(V, self._selection.value)

    @property
    def number(self) -> int:
        """Which of the Value's Encodings this is, counting from 1."""
        return self._selection.number

    @property
    def positions(self) -> list[Position]:
        """The Field's Channels in this Encoding, in `channels` order."""
        return self._selection.positions

    def set(self) -> None:
        """Sets the Value using this Encoding. Needs a session."""
        self._dut._write(self._selection)

    def __repr__(self) -> str:
        return self._selection.describe()


class _Selection:
    """One Encoding of one Value of a Field, with the Channel bits it sets."""

    __slots__ = ("bits", "count", "field", "number", "value")

    def __init__(self, field: Field[Any], value: str, number: int, count: int, bits: int) -> None:
        self.field = field
        self.value = value
        """The Value, never an alias."""
        self.number = number
        """Which Encoding, counting from 1."""
        self.count = count
        """How many Encodings the Value has."""
        self.bits = bits

    @property
    def positions(self) -> list[Position]:
        """The Field's Channels in this Encoding, in `channels` order."""
        return self.field._positions(self.bits)

    @property
    def label(self) -> str:
        """The Field and Value, such as `mode="night"`."""
        return f'{self.field.name}="{self.value}"'

    def describe(self) -> str:
        """Such as `mode="night" Encoding 2 of 3 ["on", "on", "off"]`."""
        return f"{self.label} Encoding {self.number} of {self.count} {_show(self.positions)}"


class Profile:
    """Base class of a DUT model's Profile. Subclass it and declare each Field with `field()`."""

    _fields: dict[str, Field[Any]]

    def __init_subclass__(cls) -> None:
        own: dict[str, Field[Any]] = {k: v for k, v in vars(cls).items() if isinstance(v, Field)}
        _check_repeated_values(cls, own)
        for f in own.values():
            f._check()
        cls._fields = {**getattr(super(cls, cls), "_fields", {}), **own}

    def __init__(self, rig: Rig) -> None:
        self._rig = rig
        self._batch: dict[Field[Any], _Selection] | None = None
        """The Encoding each Field was last set to in the open batch, in first-set order."""

    @contextmanager
    def batch(self) -> Generator[None]:
        """Changes several Fields together, in one write when the block ends. Needs a session.

        Setting a Field twice keeps the last Value. If two Fields need a shared Channel in
        different positions, raises `BatchConflictError` and changes nothing.
        """
        if self._batch is not None:
            yield
            return
        self._batch = {}
        try:
            yield
            batch = self._batch
        finally:
            self._batch = None
        if not batch:
            return
        mask = values = 0
        for selection in batch.values():
            field_mask, bits = selection.field._mask, selection.bits
            if clash := mask & field_mask & (values ^ bits):
                bit = clash & -clash
                other = next(s for s in batch.values() if s.field._mask & bit)
                needs, other_needs = _position(bits, bit), _position(~bits, bit)
                raise BatchConflictError(
                    f"CH{bit.bit_length()}: {other.label} needs {other_needs}, but "
                    f"{selection.label} needs {needs}. Set only one of them in a batch, or pick "
                    "Values that agree. No Channels were changed."
                )
            mask |= field_mask
            values = values & ~field_mask | bits
        self._rig._write_channels(mask, values)

    def __str__(self) -> str:
        """Every Field's current Value on one line, for a test log."""
        state = self._rig._read_channels()
        return f"{type(self).__name__}({', '.join(f._show(state) for f in self._fields.values())})"

    def _write(self, selection: _Selection) -> None:
        """Writes one Field's Encoding, or keeps it for the open batch.

        Every Field write goes through here.
        """
        if self._batch is not None:
            self._batch[selection.field] = selection
        else:
            self._rig._write_channels(selection.field._mask, selection.bits)


def _check_repeated_values(cls: type[Profile], fields: dict[str, Field[Any]]) -> None:
    """Raises `ProfileError` for a Value name listed twice in one Field.

    Python keeps only the last of two equal dict keys, so this reads the Profile's source.
    A Profile with no source file, typed into a REPL say, isn't checked.
    """
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    except (OSError, TypeError, SyntaxError):
        return
    body = tree.body[0].body if tree.body and isinstance(tree.body[0], ast.ClassDef) else []
    for statement in body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
        elif isinstance(statement, ast.AnnAssign):
            target = statement.target
        else:
            continue
        if not (
            isinstance(target, ast.Name)
            and target.id in fields
            and isinstance(call := statement.value, ast.Call)
        ):
            continue
        values = next((k.value for k in call.keywords if k.arg == "values"), None)
        if values is None and len(call.args) > 1:
            values = call.args[1]
        if not isinstance(values, ast.Dict):
            continue
        seen: set[str] = set()
        for key in values.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                if key.value in seen:
                    raise ProfileError(
                        f'{fields[target.id]._where}: the Value "{key.value}" is listed twice, '
                        "and Python keeps only the last one. Give each Value its own name, or "
                        "make one an alias."
                    )
                seen.add(key.value)


def _show(positions: Sequence[str]) -> str:
    """Positions the way a Profile lists them: `["on", "off"]`."""
    return "[" + ", ".join(f'"{position}"' for position in positions) + "]"


def _position(bits: int, channel_bit: int) -> Position:
    return "on" if bits & channel_bit else "off"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _did_you_mean(name: object, names: list[str]) -> str:
    close = difflib.get_close_matches(str(name), names, n=1)
    return f' Did you mean "{close[0]}"?' if close else ""
