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
            lock_status=_FakeLockStatus(
                doors=_FakeDoors(driver_seat=_NoLockedAttr())
            )
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
    """DOOR_LOCK_DESCRIPTION has the expected key and icon."""
    assert DOOR_LOCK_DESCRIPTION.key == "door_lock"
    assert DOOR_LOCK_DESCRIPTION.icon == "mdi:car-door-lock"
