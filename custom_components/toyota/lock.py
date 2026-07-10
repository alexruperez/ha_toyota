"""Lock platform for Toyota integration.

Exposes a single lock entity per vehicle that sends door-lock / door-unlock
remote commands through the pytoyoda ``post_command`` API.  The entity is
only registered when the vehicle reports ``door_lock_unlock_capable`` (via
``extended_capabilities``) or ``dlock_unlock_capable`` (via
``remote_service_capabilities``).

After a lock/unlock command is dispatched the integration triggers
``toyota.refresh_vehicle_status`` so the coordinator fetches fresh door-state
data without waiting for the next polling cycle.  While the refresh is in
flight the entity uses an *optimistic* assumed state so that HA shows the
expected lock/unlock state immediately instead of reverting to "unknown".
The optimistic state is cleared as soon as the coordinator delivers the first
fresh status update after the command.

.. note::
    Some Toyota models do **not** support remote unlock when the doors were
    locked with the physical key rather than via the app or remote.  In that
    case the ``door-unlock`` command will be rejected by the Toyota gateway
    and Home Assistant will surface the error as a service-call failure.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.core import callback
from pytoyoda.models.endpoints.command import CommandType

from .const import DOMAIN
from .entity import ToyotaBaseEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
    from pytoyoda.models.vehicle import Vehicle

    from . import VehicleData

_LOGGER = logging.getLogger(__name__)

DOOR_LOCK_DESCRIPTION = LockEntityDescription(
    key="door_lock",
    translation_key="door_lock",
)


def _is_lock_capable(vehicle: Vehicle) -> bool:
    """Return True when the vehicle supports remote door lock / unlock.

    Checks two independent capability models exposed by pytoyoda so that
    the entity is created whenever at least one flag signals support,
    regardless of which API response populated it.
    """
    extended = getattr(vehicle._vehicle_info, "extended_capabilities", None)  # noqa: SLF001
    if getattr(extended, "door_lock_unlock_capable", False):
        return True

    remote = getattr(vehicle._vehicle_info, "remote_service_capabilities", None)  # noqa: SLF001
    return bool(getattr(remote, "dlock_unlock_capable", False))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Toyota lock entities from a config entry."""
    coordinator: DataUpdateCoordinator[list[VehicleData]] = hass.data[DOMAIN][
        entry.entry_id
    ]

    async_add_entities(
        ToyotaLockEntity(
            coordinator=coordinator,
            entry_id=entry.entry_id,
            vehicle_index=index,
            description=DOOR_LOCK_DESCRIPTION,
        )
        for index, vehicle_data in enumerate(coordinator.data)
        if _is_lock_capable(vehicle_data["data"])
    )


class ToyotaLockEntity(ToyotaBaseEntity, LockEntity):
    """Lock entity representing the central door-lock state of a Toyota vehicle.

    State is derived from the driver-seat door lock reported by the Toyota
    Connected Services status endpoint.  ``None`` (unknown) is returned when
    the car has not yet transmitted a status update so that HA shows the
    entity as *unknown* rather than falsely locked or unlocked.

    Sending a lock/unlock command via ``async_lock`` / ``async_unlock``
    dispatches the remote command and then requests an immediate coordinator
    refresh so the updated state is reflected in HA without waiting for the
    next polling cycle.  While the refresh is in flight an optimistic state
    is applied so the UI shows the expected state immediately.
    """

    def __init__(self, **kwargs: object) -> None:
        """Initialise the lock entity with no optimistic state."""
        super().__init__(**kwargs)
        # Optimistic lock state set immediately after a successful command.
        # Cleared on the next coordinator update so real data takes priority.
        self._assumed_locked: bool | None = None
        # Last confirmed lock state (True/False). Used as fallback when the
        # API returns None for driver_seat.locked so the entity never reverts
        # to "unknown" once a real state has been observed.
        self._last_known_locked: bool | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Clear optimistic state only when genuinely fresh data arrives.

        If the coordinator fired because a refresh failed (served cached or stub
        data), keep the optimistic state so the UI does not revert to 'unknown'
        while the car is still processing the command.  Real data displaces the
        optimistic state on the next successful status fetch.
        """
        if self._assumed_locked is not None:
            try:
                vd = self.coordinator.data[self.index]
                is_fresh = (
                    not vd.get("is_cached")
                    and vd.get("last_successful_fetch") is not None
                )
            except (IndexError, TypeError):
                is_fresh = False
            if is_fresh:
                self._assumed_locked = None
        super()._handle_coordinator_update()

    @property
    def icon(self) -> str:
        """Return lock/unlock icon based on current state."""
        if self.is_locked is False:
            return "mdi:car-door-lock-open"
        return "mdi:car-door-lock"

    @property
    def is_locked(self) -> bool | None:
        """Return True when the driver-seat door is locked, None when unknown.

        Returns the optimistic state if a lock/unlock command has been sent
        and the coordinator has not yet confirmed the result.  Otherwise
        reads the live state from the status endpoint.

        When the API returns None for driver_seat.locked (e.g. Toyota omits
        the field in certain status responses) the last real state is returned
        as a fallback so the entity does not unnecessarily revert to "unknown".
        External state changes (key fob, MyToyota app, etc.) are still picked
        up correctly whenever the API does include a valid value.
        """
        if self._assumed_locked is not None:
            return self._assumed_locked
        lock_status = getattr(self.vehicle, "lock_status", None)
        if lock_status is not None:
            doors = getattr(lock_status, "doors", None)
            if doors is not None:
                driver_seat = getattr(doors, "driver_seat", None)
                real_state = getattr(driver_seat, "locked", None)
                if real_state is not None:
                    # Update last-known state whenever the API reports a value,
                    # regardless of whether the change came from HA or externally
                    # (key fob, MyToyota app, etc.).
                    self._last_known_locked = real_state
                    return real_state
        # API returned no lock data - keep the last known state so the entity
        # does not flip to "unknown" while the car is temporarily silent.
        return self._last_known_locked

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return last-updated timestamp as a diagnostic attribute."""
        lock_status = getattr(self.vehicle, "lock_status", None)
        return {
            "last_updated": getattr(lock_status, "last_updated", None)
            if lock_status
            else None,
        }

    async def async_lock(self, **_kwargs: object) -> None:
        """Send door-lock command to the vehicle."""
        await self._async_send_command(CommandType.DOOR_LOCK, assumed_locked=True)

    async def async_unlock(self, **_kwargs: object) -> None:
        """Send door-unlock command to the vehicle."""
        await self._async_send_command(CommandType.DOOR_UNLOCK, assumed_locked=False)

    async def _async_send_command(
        self, command: CommandType, *, assumed_locked: bool
    ) -> None:
        """Dispatch *command*, apply optimistic state, and schedule a refresh.

        The post_command coroutine sends the remote command to the Toyota
        gateway.  On success the entity immediately reports the expected
        lock/unlock state (optimistic) before the coordinator has a chance
        to poll for the actual status.  The optimistic state is cleared on
        the next coordinator update so real data takes priority.

        Any exception from post_command propagates to the caller so Home
        Assistant can surface it as a service-call failure.
        """
        _LOGGER.debug(
            "Sending remote command %s to vehicle vin=...%s",
            command.value,
            (self.vehicle.vin or "")[-6:],
        )
        await self.vehicle.post_command(command)

        # Apply optimistic state immediately so the UI reflects the expected
        # outcome without waiting for the full refresh cycle.
        self._assumed_locked = assumed_locked
        self.async_write_ha_state()

        await self._async_request_refresh()

    async def _async_request_refresh(self) -> None:
        """Trigger refresh_vehicle_status for this vehicle's HA device."""
        from homeassistant.helpers import device_registry as dr  # noqa: PLC0415

        device_reg = dr.async_get(self.hass)
        device = device_reg.async_get_device(
            identifiers={(DOMAIN, self.vehicle.vin or "")}
        )
        if device is None:
            _LOGGER.debug(
                "No HA device found for vin=...%s; skipping status refresh",
                (self.vehicle.vin or "")[-6:],
            )
            return

        await self.hass.services.async_call(
            DOMAIN,
            "refresh_vehicle_status",
            {"device_id": [device.id]},
            blocking=False,
        )
