"""Unit tests for the Toyota lock platform (_is_lock_capable + entity properties).

These tests exercise the pure/cheap logic in lock.py without spinning up a
full HA instance or network stack.  The async command-dispatch path
(_async_send_command, _async_request_refresh) requires a live hass fixture
and is therefore left for integration/end-to-end tests.
"""

from __future__ import annotations

from custom_components.toyota.lock import (
    DOOR_LOCK_DESCRIPTION,
    ToyotaLockEntity,
    _is_lock_capable,
)

# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------


class _FakeExtendedCapabilities:
    def __init__(self, *, door_lock_unlock_capable: bool = False) -> None:
        self.door_lock_unlock_capable = door_lock_unlock_capable


class _FakeRemoteServiceCapabilities:
    def __init__(self, *, dlock_unlock_capable: bool = False) -> None:
        self.dlock_unlock_capable = dlock_unlock_capable


class _FakeVehicleInfo:
    def __init__(
        self,
        extended_capabilities=None,
        remote_service_capabilities=None,
    ) -> None:
        self.extended_capabilities = extended_capabilities
        self.remote_service_capabilities = remote_service_capabilities


class _FakeVehicle:
    """Minimal Vehicle stub."""

    vin = "JTDKN3DU8A0123456"

    def __init__(self, *, info=None, lock_status=None) -> None:
        self._vehicle_info = info or _FakeVehicleInfo()
        self.lock_status = lock_status


class _FakeDoor:
    def __init__(self, *, locked: bool | None = None) -> None:
        self.locked = locked


class _FakeDoors:
    def __init__(self, *, driver_seat: _FakeDoor | None = None) -> None:
        self.driver_seat = driver_seat


class _FakeLockStatus:
    def __init__(self, *, doors=None, last_updated=None) -> None:
        self.doors = doors
        self.last_updated = last_updated


class _FakeCoordinator:
    """Minimal DataUpdateCoordinator stub for entity construction."""

    def __init__(self, vehicle: _FakeVehicle) -> None:
        self.data = [{"data": vehicle, "statistics": None}]

    def async_add_listener(self, *_args, **_kwargs):
        """No-op."""
        return lambda: None


# ---------------------------------------------------------------------------
# Helper to build a ToyotaLockEntity without hass
# ---------------------------------------------------------------------------


def _make_entity(vehicle: _FakeVehicle) -> ToyotaLockEntity:
    coordinator = _FakeCoordinator(vehicle)
    entity = ToyotaLockEntity.__new__(ToyotaLockEntity)
    # Manually mirror the attributes that ToyotaBaseEntity.__init__ would set so
    # that property accessors work without a live hass / coordinator loop.
    entity.coordinator = coordinator
    entity.index = 0
    entity.vehicle = vehicle
    entity.entity_description = DOOR_LOCK_DESCRIPTION
    # Initialise the optimistic-state attributes added in ToyotaLockEntity.__init__.
    entity._assumed_locked = None  # noqa: SLF001
    entity._last_known_locked = None  # noqa: SLF001
    return entity


# ---------------------------------------------------------------------------
# _is_lock_capable
# ---------------------------------------------------------------------------


class TestIsLockCapable:
    """Test the capability-detection helper."""

    def test_no_capabilities_returns_false(self):
        """Vehicle with no capability objects → not capable."""
        vehicle = _FakeVehicle(info=_FakeVehicleInfo())
        assert _is_lock_capable(vehicle) is False

    def test_extended_capable_true(self):
        """door_lock_unlock_capable=True → capable."""
        info = _FakeVehicleInfo(
            extended_capabilities=_FakeExtendedCapabilities(
                door_lock_unlock_capable=True
            )
        )
        assert _is_lock_capable(_FakeVehicle(info=info)) is True

    def test_extended_capable_false_only(self):
        """door_lock_unlock_capable=False and no remote cap → not capable."""
        info = _FakeVehicleInfo(
            extended_capabilities=_FakeExtendedCapabilities(
                door_lock_unlock_capable=False
            )
        )
        assert _is_lock_capable(_FakeVehicle(info=info)) is False

    def test_remote_service_capable_true(self):
        """dlock_unlock_capable=True → capable (fallback path)."""
        info = _FakeVehicleInfo(
            remote_service_capabilities=_FakeRemoteServiceCapabilities(
                dlock_unlock_capable=True
            )
        )
        assert _is_lock_capable(_FakeVehicle(info=info)) is True

    def test_remote_service_capable_false_only(self):
        """dlock_unlock_capable=False → not capable."""
        info = _FakeVehicleInfo(
            remote_service_capabilities=_FakeRemoteServiceCapabilities(
                dlock_unlock_capable=False
            )
        )
        assert _is_lock_capable(_FakeVehicle(info=info)) is False

    def test_both_caps_false_returns_false(self):
        """Both flags False → not capable."""
        info = _FakeVehicleInfo(
            extended_capabilities=_FakeExtendedCapabilities(
                door_lock_unlock_capable=False
            ),
            remote_service_capabilities=_FakeRemoteServiceCapabilities(
                dlock_unlock_capable=False
            ),
        )
        assert _is_lock_capable(_FakeVehicle(info=info)) is False

    def test_both_caps_true_returns_true(self):
        """Both flags True → capable (extended wins, but either is sufficient)."""
        info = _FakeVehicleInfo(
            extended_capabilities=_FakeExtendedCapabilities(
                door_lock_unlock_capable=True
            ),
            remote_service_capabilities=_FakeRemoteServiceCapabilities(
                dlock_unlock_capable=True
            ),
        )
        assert _is_lock_capable(_FakeVehicle(info=info)) is True

    def test_vehicle_info_is_none(self):
        """_vehicle_info is None → getattr returns None → not capable."""
        vehicle = _FakeVehicle()
        vehicle._vehicle_info = None  # noqa: SLF001
        assert _is_lock_capable(vehicle) is False


# ---------------------------------------------------------------------------
# ToyotaLockEntity.is_locked
# ---------------------------------------------------------------------------


class TestIsLocked:
    """Test the is_locked property."""

    def test_locked_true(self):
        """Driver seat locked=True → is_locked is True."""
        vehicle = _FakeVehicle(
            lock_status=_FakeLockStatus(
                doors=_FakeDoors(driver_seat=_FakeDoor(locked=True))
            )
        )
        entity = _make_entity(vehicle)
        assert entity.is_locked is True

    def test_locked_false(self):
        """Driver seat locked=False → is_locked is False."""
        vehicle = _FakeVehicle(
            lock_status=_FakeLockStatus(
                doors=_FakeDoors(driver_seat=_FakeDoor(locked=False))
            )
        )
        entity = _make_entity(vehicle)
        assert entity.is_locked is False

    def test_locked_none_when_no_lock_status(self):
        """No lock_status → is_locked is None (unknown)."""
        vehicle = _FakeVehicle(lock_status=None)
        entity = _make_entity(vehicle)
        assert entity.is_locked is None

    def test_locked_none_when_no_doors(self):
        """lock_status present but doors=None → is_locked is None."""
        vehicle = _FakeVehicle(lock_status=_FakeLockStatus(doors=None))
        entity = _make_entity(vehicle)
        assert entity.is_locked is None

    def test_locked_none_when_no_driver_seat(self):
        """Doors present but no driver_seat → is_locked is None."""
        vehicle = _FakeVehicle(
            lock_status=_FakeLockStatus(doors=_FakeDoors(driver_seat=None))
        )
        entity = _make_entity(vehicle)
        assert entity.is_locked is None

    def test_locked_none_when_locked_attr_missing(self):
        """driver_seat has no 'locked' attribute → is_locked is None."""

        class _NoLockedAttr:
            pass

        vehicle = _FakeVehicle(
            lock_status=_FakeLockStatus(doors=_FakeDoors(driver_seat=_NoLockedAttr()))
        )
        entity = _make_entity(vehicle)
        assert entity.is_locked is None


# ---------------------------------------------------------------------------
# ToyotaLockEntity.extra_state_attributes
# ---------------------------------------------------------------------------


class TestExtraStateAttributes:
    """Test diagnostic attributes returned by the entity."""

    def test_last_updated_present(self):
        """last_updated from lock_status is surfaced as an attribute."""
        ts = "2025-01-01T12:00:00Z"
        vehicle = _FakeVehicle(lock_status=_FakeLockStatus(last_updated=ts))
        entity = _make_entity(vehicle)
        attrs = entity.extra_state_attributes
        assert attrs["last_updated"] == ts

    def test_last_updated_none_when_no_lock_status(self):
        """When lock_status is None, last_updated attribute is None."""
        vehicle = _FakeVehicle(lock_status=None)
        entity = _make_entity(vehicle)
        assert entity.extra_state_attributes["last_updated"] is None

    def test_returns_dict(self):
        """extra_state_attributes always returns a dict."""
        vehicle = _FakeVehicle()
        entity = _make_entity(vehicle)
        assert isinstance(entity.extra_state_attributes, dict)


# ---------------------------------------------------------------------------
# Entity description sanity
# ---------------------------------------------------------------------------


def test_door_lock_description_key():
    """DOOR_LOCK_DESCRIPTION has the expected key; icon is dynamic on the entity."""
    assert DOOR_LOCK_DESCRIPTION.key == "door_lock"
    # Icon is no longer static on the description: ToyotaLockEntity.icon returns
    # mdi:car-door-lock or mdi:car-door-lock-open depending on is_locked state.
    assert DOOR_LOCK_DESCRIPTION.icon is None


# ---------------------------------------------------------------------------
# ToyotaLockEntity.icon (dynamic)
# ---------------------------------------------------------------------------


class TestIcon:
    """Test the dynamic icon property."""

    def test_icon_locked(self):
        """Locked state → mdi:car-door-lock."""
        vehicle = _FakeVehicle(
            lock_status=_FakeLockStatus(
                doors=_FakeDoors(driver_seat=_FakeDoor(locked=True))
            )
        )
        entity = _make_entity(vehicle)
        assert entity.icon == "mdi:car-door-lock"

    def test_icon_unlocked(self):
        """Unlocked state → mdi:car-door-lock-open."""
        vehicle = _FakeVehicle(
            lock_status=_FakeLockStatus(
                doors=_FakeDoors(driver_seat=_FakeDoor(locked=False))
            )
        )
        entity = _make_entity(vehicle)
        assert entity.icon == "mdi:car-door-lock-open"

    def test_icon_unknown(self):
        """Unknown state (None) → mdi:car-door-lock (default)."""
        entity = _make_entity(_FakeVehicle(lock_status=None))
        assert entity.icon == "mdi:car-door-lock"

    def test_icon_optimistic_locked(self):
        """Optimistic locked state → mdi:car-door-lock."""
        entity = _make_entity(_FakeVehicle(lock_status=None))
        entity._assumed_locked = True  # noqa: SLF001
        assert entity.icon == "mdi:car-door-lock"

    def test_icon_optimistic_unlocked(self):
        """Optimistic unlocked state → mdi:car-door-lock-open."""
        entity = _make_entity(_FakeVehicle(lock_status=None))
        entity._assumed_locked = False  # noqa: SLF001
        assert entity.icon == "mdi:car-door-lock-open"


# ---------------------------------------------------------------------------
# ToyotaLockEntity._handle_coordinator_update (optimistic state management)
# ---------------------------------------------------------------------------


class _FakeCoordinatorWithData:
    """Coordinator stub with configurable VehicleData entries."""

    def __init__(
        self, vehicle: _FakeVehicle, *, is_cached: bool, last_successful_fetch
    ) -> None:
        self.data = [
            {
                "data": vehicle,
                "statistics": None,
                "metric_values": True,
                "is_cached": is_cached,
                "last_successful_fetch": last_successful_fetch,
            }
        ]

    def async_add_listener(self, *_args, **_kwargs):
        return lambda: None


def _make_entity_with_coordinator(vehicle, coordinator) -> ToyotaLockEntity:
    entity = ToyotaLockEntity.__new__(ToyotaLockEntity)
    entity.coordinator = coordinator
    entity.index = 0
    entity.vehicle = vehicle
    entity.entity_description = DOOR_LOCK_DESCRIPTION
    entity._assumed_locked = None  # noqa: SLF001
    entity._last_known_locked = None  # noqa: SLF001
    # async_write_ha_state requires a live hass instance; stub it out for unit tests.
    entity.async_write_ha_state = lambda: None  # type: ignore[method-assign]
    return entity


class TestHandleCoordinatorUpdate:
    """Test that optimistic state is only cleared on fresh data."""

    def test_clears_optimistic_on_fresh_data(self):
        """Fresh non-cached data clears the optimistic state."""
        from datetime import datetime

        vehicle = _FakeVehicle()
        coordinator = _FakeCoordinatorWithData(
            vehicle, is_cached=False, last_successful_fetch=datetime.now()
        )
        entity = _make_entity_with_coordinator(vehicle, coordinator)
        entity._assumed_locked = True  # noqa: SLF001

        entity._handle_coordinator_update()  # noqa: SLF001

        assert entity._assumed_locked is None  # noqa: SLF001

    def test_keeps_optimistic_on_failed_refresh(self):
        """Failed refresh (stub with last_successful_fetch=None) keeps optimistic state."""
        vehicle = _FakeVehicle()
        coordinator = _FakeCoordinatorWithData(
            vehicle, is_cached=False, last_successful_fetch=None
        )
        entity = _make_entity_with_coordinator(vehicle, coordinator)
        entity._assumed_locked = True  # noqa: SLF001

        entity._handle_coordinator_update()  # noqa: SLF001

        assert entity._assumed_locked is True  # noqa: SLF001

    def test_keeps_optimistic_on_cached_data(self):
        """Cached data (retain-on-transient) keeps optimistic state."""
        from datetime import datetime

        vehicle = _FakeVehicle()
        coordinator = _FakeCoordinatorWithData(
            vehicle, is_cached=True, last_successful_fetch=datetime.now()
        )
        entity = _make_entity_with_coordinator(vehicle, coordinator)
        entity._assumed_locked = False  # noqa: SLF001

        entity._handle_coordinator_update()  # noqa: SLF001

        assert entity._assumed_locked is False  # noqa: SLF001

    def test_no_assumed_state_is_noop(self):
        """When _assumed_locked is None, update passes through without error."""
        from datetime import datetime

        vehicle = _FakeVehicle()
        coordinator = _FakeCoordinatorWithData(
            vehicle, is_cached=False, last_successful_fetch=datetime.now()
        )
        entity = _make_entity_with_coordinator(vehicle, coordinator)
        # No assumed state — should not raise.
        entity._handle_coordinator_update()  # noqa: SLF001
        assert entity._assumed_locked is None  # noqa: SLF001

    def test_fresh_data_preserves_assumed_as_last_known_when_api_omits_lock_field(
        self,
    ):
        """Regression: fresh data clears optimistic state but preserves it in
        _last_known_locked so is_locked does not flip to None (unknown) when the
        Toyota API omits driver_seat.locked from the status response.

        This reproduces the observed pattern where the lock entity goes to
        'unknown' ~6 minutes after a lock/unlock action (next polling cycle)
        because the API never includes driver_seat.locked for the vehicle.
        """
        from datetime import datetime

        # Vehicle whose API response has no lock data (driver_seat.locked = None)
        vehicle = _FakeVehicle(lock_status=None)
        coordinator = _FakeCoordinatorWithData(
            vehicle, is_cached=False, last_successful_fetch=datetime.now()
        )
        entity = _make_entity_with_coordinator(vehicle, coordinator)
        # Simulate: user sent lock command → optimistic True, _last_known_locked
        # still None (never received real API lock data before).
        entity._assumed_locked = True  # noqa: SLF001

        entity._handle_coordinator_update()  # noqa: SLF001

        # Optimistic state cleared (fresh data arrived).
        assert entity._assumed_locked is None  # noqa: SLF001
        # _last_known_locked was populated from the optimistic state so
        # is_locked does not fall back to None (unknown).
        assert entity._last_known_locked is True  # noqa: SLF001
        assert entity.is_locked is True

    def test_fresh_real_api_data_overrides_last_known_from_assumed(self):
        """When fresh API data includes driver_seat.locked, that real value wins
        over any previous _last_known_locked set from the optimistic state.
        """
        from datetime import datetime

        vehicle = _FakeVehicle(
            lock_status=_FakeLockStatus(
                doors=_FakeDoors(driver_seat=_FakeDoor(locked=False))
            )
        )
        coordinator = _FakeCoordinatorWithData(
            vehicle, is_cached=False, last_successful_fetch=datetime.now()
        )
        entity = _make_entity_with_coordinator(vehicle, coordinator)
        # Simulate unlock command: optimistic False, but the API might say True
        # (e.g., car hasn't processed the command yet).
        entity._assumed_locked = False  # noqa: SLF001

        entity._handle_coordinator_update()  # noqa: SLF001

        # After _handle_coordinator_update, _last_known_locked is initially set
        # from _assumed_locked (False). Then is_locked() is called by
        # async_write_ha_state and sees driver_seat.locked=False, confirming it.
        assert entity._assumed_locked is None  # noqa: SLF001
        # The real API value (False) is reflected.
        assert entity.is_locked is False
