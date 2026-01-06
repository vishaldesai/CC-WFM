from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, List, Tuple


MONTH_ABBR = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def parse_forecast_timestamp(ts: str) -> datetime:
    """
    Parse 'DD-MON-YYYY HH24:MI:SS' where MON is uppercase JAN..DEC.
    Example: '01-JAN-2026 06:00:00'
    """
    try:
        dpart, tpart = ts.split(" ")
        dd_s, mon_s, yyyy_s = dpart.split("-")
        hh_s, mm_s, ss_s = tpart.split(":")
        return datetime(
            int(yyyy_s),
            MONTH_ABBR[mon_s.upper()],
            int(dd_s),
            int(hh_s),
            int(mm_s),
            int(ss_s),
        )
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Invalid forecast timestamp: {ts!r}") from e


@dataclass(frozen=True)
class TimeIndex:
    start_date: date
    days: int
    bucket_minutes: int

    @property
    def buckets_per_day(self) -> int:
        return int(24 * 60 / self.bucket_minutes)

    def day_bucket_from_dt(self, dt: datetime) -> Tuple[int, int]:
        day_idx = (dt.date() - self.start_date).days
        if day_idx < 0 or day_idx >= self.days:
            raise ValueError(f"datetime {dt.isoformat()} out of horizon [{self.start_date}, days={self.days}]")
        minute_of_day = dt.hour * 60 + dt.minute
        if minute_of_day % self.bucket_minutes != 0:
            raise ValueError(f"datetime {dt.isoformat()} not aligned to bucket_minutes={self.bucket_minutes}")
        bucket_idx = minute_of_day // self.bucket_minutes
        if bucket_idx < 0 or bucket_idx >= self.buckets_per_day:
            raise ValueError(f"bucket_idx {bucket_idx} out of range")
        return day_idx, bucket_idx

    def dt_from_day_bucket(self, day_idx: int, bucket_idx: int) -> datetime:
        if day_idx < 0 or day_idx >= self.days:
            raise ValueError("day_idx out of range")
        if bucket_idx < 0 or bucket_idx >= self.buckets_per_day:
            raise ValueError("bucket_idx out of range")
        d = self.start_date + timedelta(days=day_idx)
        minutes = bucket_idx * self.bucket_minutes
        hh = minutes // 60
        mm = minutes % 60
        return datetime(d.year, d.month, d.day, hh, mm, 0)

    def iter_day_buckets(self) -> Iterable[Tuple[int, int]]:
        for d in range(self.days):
            for b in range(self.buckets_per_day):
                yield d, b

    def week_of_day(self, day_idx: int) -> int:
        # Simple 0-based week blocks of 7 days, aligned to start_date.
        return day_idx // 7

    def weeks(self) -> List[int]:
        return list(range((self.days + 6) // 7))

