from dataclasses import dataclass
from datetime import datetime, date, time
from typing import List, Union, Tuple


@dataclass
class Entry:
    entry_id: int
    entry_date: date
    start_time: time
    end_time: time
    title: str
    provider: str
    note: str
    is_selected: bool

    def __init__(
            self,
             entry_id: int,
            entry_date: Union[date, str],
            start_time: Union[time, str],
            end_time: Union[time, str],
            title: str = None,
            provider: str = None,
            note: str = None,
            is_selected: bool = False):
        self.entry_id = entry_id
        self.entry_date = self._parse_date(entry_date)
        self.start_time = self._parse_time(start_time)
        self.end_time = self._parse_time(end_time)
        self.title = title
        self.provider = provider
        self.note = note
        self.is_selected = is_selected

    @staticmethod
    def _parse_date(value: Union[date, str]) -> date:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            # entry_date is stored as ISO YYYY-MM-DD
            return datetime.strptime(value, "%Y-%m-%d").date()
        raise TypeError(f"Expected str or date for entry_date, got {type(value).__name__}")

    @staticmethod
    def _parse_time(value: Union[time, str]) -> time:
        if isinstance(value, time):
            return value
        if isinstance(value, str):
            # start_time / end_time stored as HH:MM:SS
            return datetime.strptime(value, "%H:%M:%S").time()
        raise TypeError(f"Expected str or time for time field, got {type(value).__name__}")


@dataclass
class DateRange:
    date_from: datetime
    date_to: datetime

    def __init__(self, date_from: datetime, date_to: datetime):
        self.date_from = self._parse_datetime(date_from)
        self.date_to = self._parse_datetime(date_to)

    @staticmethod
    def _parse_datetime(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        raise TypeError(f"Expected str or datetime, got {type(value).__name__}")

    def to_primitive(self) -> dict:
        """Safe to store this into Flask's session."""
        return {
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
        }

    @classmethod
    def from_primitive(cls, data: dict) -> "DateRange":
        return cls(
            date_from=data["date_from"],
            date_to=data["date_to"],
        )

@dataclass
class Schedule:
    daterange: DateRange
    entries: List[Entry]

    def __init__(self, daterange: DateRange, entries: List[Entry] = None):
        self.daterange = daterange
        self.entries = entries

