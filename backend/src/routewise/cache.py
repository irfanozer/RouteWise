from collections import OrderedDict
from dataclasses import dataclass

from routewise.domain import RoutePlan

BASELINE_DISRUPTION_VERSION = "baseline"


@dataclass(frozen=True, slots=True)
class RouteCacheKey:
    network_version: str
    disruption_version: str
    origin_id: str
    destination_id: str
    objective: str
    wheelchair_required: bool
    max_transfers: int | None


class RouteCache:
    """A small process-local LRU cache whose keys describe all routing inputs."""

    def __init__(self, max_entries: int = 512) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._entries: OrderedDict[RouteCacheKey, RoutePlan | None] = OrderedDict()

    def get(self, key: RouteCacheKey) -> tuple[bool, RoutePlan | None]:
        if key not in self._entries:
            return False, None
        value = self._entries.pop(key)
        self._entries[key] = value
        return True, value

    def put(self, key: RouteCacheKey, value: RoutePlan | None) -> None:
        self._entries.pop(key, None)
        self._entries[key] = value
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def invalidate_for_disruption_version(self, active_version: str) -> int:
        stale_keys = [
            key
            for key in self._entries
            if key.disruption_version not in {BASELINE_DISRUPTION_VERSION, active_version}
        ]
        for key in stale_keys:
            del self._entries[key]
        return len(stale_keys)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
