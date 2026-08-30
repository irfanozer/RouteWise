from routewise.cache import BASELINE_DISRUPTION_VERSION, RouteCache, RouteCacheKey


def make_key(version: str, origin: str = "a") -> RouteCacheKey:
    return RouteCacheKey(
        network_version="network-v1",
        disruption_version=version,
        origin_id=origin,
        destination_id="z",
        objective="fastest",
        wheelchair_required=False,
        max_transfers=None,
    )


def test_cache_distinguishes_a_cached_unavailable_route_from_a_miss() -> None:
    cache = RouteCache(max_entries=2)
    key = make_key("scenario-v1")

    assert cache.get(key) == (False, None)
    cache.put(key, None)
    assert cache.get(key) == (True, None)


def test_cache_is_bounded_and_evicts_least_recently_used() -> None:
    cache = RouteCache(max_entries=2)
    first = make_key("v1", "a")
    second = make_key("v1", "b")
    third = make_key("v1", "c")
    cache.put(first, None)
    cache.put(second, None)
    cache.get(first)
    cache.put(third, None)

    assert cache.get(first)[0] is True
    assert cache.get(second)[0] is False
    assert cache.get(third)[0] is True


def test_new_disruption_version_invalidates_old_scenario_but_not_baseline() -> None:
    cache = RouteCache(max_entries=8)
    baseline = make_key(BASELINE_DISRUPTION_VERSION)
    old = make_key("scenario-v1")
    active = make_key("scenario-v2")
    for key in (baseline, old, active):
        cache.put(key, None)

    removed = cache.invalidate_for_disruption_version("scenario-v2")

    assert removed == 1
    assert cache.get(baseline)[0] is True
    assert cache.get(old)[0] is False
    assert cache.get(active)[0] is True
