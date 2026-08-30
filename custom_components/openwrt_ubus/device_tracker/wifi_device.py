"""Device tracker entity for OpenWrt Ubus WiFi Presence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.openwrt_ubus.const import CONF_HOST, DOMAIN, TRACKER_UNIQUE_ID_PREFIX
from custom_components.openwrt_ubus.data import (
    OpenWrtUbusWifiPresenceConfigEntry,
    TrackerTarget,
    TrackerTargetType,
    WifiPresenceDevice,
    association_preference,
)
from custom_components.openwrt_ubus.entity import OpenWrtUbusWifiPresenceEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import ScannerEntity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import slugify

if TYPE_CHECKING:
    from custom_components.openwrt_ubus.device_tracker import OpenWrtUbusWifiPresenceTrackerManager


class OpenWrtUbusWifiPresenceDeviceTracker(ScannerEntity, OpenWrtUbusWifiPresenceEntity):
    """Represents one WiFi client tracker target."""

    _attr_source_type = SourceType.ROUTER

    def __init__(
        self,
        coordinator,
        entry: OpenWrtUbusWifiPresenceConfigEntry,
        entity_key: str,
        manager: OpenWrtUbusWifiPresenceTrackerManager | None = None,
    ) -> None:
        """Initialize tracker entity for one alias/MAC target."""
        super().__init__(coordinator)
        self._manager = manager
        self._owner_entry_id = entry.entry_id
        self._host = entry.data[CONF_HOST]
        self._entity_key = entity_key
        self._fallback_name = entity_key
        self._fallback_mac = self._extract_mac_from_entity_key(entity_key)
        self._attr_unique_id = f"{TRACKER_UNIQUE_ID_PREFIX}{self._entity_key}"
        self._attr_suggested_object_id = self._build_suggested_object_id(entity_key)
        self._attr_entity_registry_enabled_default = True

    async def async_added_to_hass(self) -> None:
        """Register the entity after Home Assistant accepted it."""
        await super().async_added_to_hass()
        if self._manager is not None:
            self._manager.async_entity_added(self)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister the entity when Home Assistant removes it."""
        if self._manager is not None:
            self._manager.async_entity_removed(self)
        await super().async_will_remove_from_hass()

    @property
    def entity_key(self) -> str:
        """Return the stable target key managed by the global platform."""
        return self._entity_key

    @property
    def owner_entry_id(self) -> str:
        """Return the config entry platform currently hosting this entity."""
        return self._owner_entry_id

    @property
    def unique_id(self) -> str:
        """Return an alias-stable ID instead of ScannerEntity's MAC-only ID."""
        return f"{TRACKER_UNIQUE_ID_PREFIX}{self._entity_key}"

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Enable explicitly selected tracker targets by default."""
        return True

    @property
    def _target(self) -> TrackerTarget | None:
        if self._manager is not None:
            return self._manager.tracker_targets.get(self._entity_key)
        return self.coordinator.tracker_targets.get(self._entity_key)

    @staticmethod
    def _extract_mac_from_entity_key(entity_key: str) -> str | None:
        """Extract MAC from mac_* tracker keys."""
        if entity_key.startswith("mac_"):
            return entity_key.removeprefix("mac_")
        return None

    @staticmethod
    def _build_suggested_object_id(entity_key: str) -> str:
        """Build suggested object id for stable entity naming."""
        if entity_key.startswith("alias_"):
            return entity_key.removeprefix("alias_")
        if entity_key.startswith("mac_"):
            mac = entity_key.removeprefix("mac_").replace(":", "").lower()
            return f"mac_{mac}"
        return slugify(entity_key, separator="_")

    @property
    def _resolved_mac(self) -> str | None:
        """Resolve current target MAC."""
        target = self._target
        if target and target.mac:
            return target.mac
        return self._fallback_mac

    def _find_device_global(self) -> tuple[WifiPresenceDevice | None, str | None]:
        """Find device across all OpenWrt router coordinators.

        Returns tuple of (device, router_host) or (None, None) if not found.
        """
        mac = self._resolved_mac
        if mac is None:
            return None, None

        if self._manager is not None:
            return self._manager.find_device(mac)

        candidates: list[tuple[WifiPresenceDevice, str]] = []
        device = self.coordinator.data.get(mac)
        if device:
            candidates.append((device, self._host))

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.state != ConfigEntryState.LOADED:
                continue
            if entry.entry_id == self.coordinator.entry.entry_id:
                continue

            runtime_data = getattr(entry, "runtime_data", None)
            if runtime_data is None:
                continue
            coordinator = getattr(runtime_data, "coordinator", None)
            if coordinator is None:
                continue

            device = coordinator.data.get(mac)
            if device:
                host = entry.data.get(CONF_HOST, "unknown")
                candidates.append((device, host))

        if candidates:
            # Mesh roaming can leave one short-lived duplicate association. Prefer
            # the station with the least inactivity, then the strongest signal.
            return min(
                candidates,
                key=lambda candidate: association_preference(candidate[0]),
            )

        return None, None

    @property
    def name(self) -> str:
        """Return display name for this tracker target."""
        target = self._target
        if target:
            self._fallback_name = target.display_name
            return target.display_name
        return self._fallback_name

    @property
    def is_connected(self) -> bool:
        """Return whether current target MAC is associated with any router."""
        device, _ = self._find_device_global()
        return device is not None

    @property
    def mac_address(self) -> str | None:
        """Return the currently mapped network MAC address."""
        return self._resolved_mac

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | int | float | None]:
        """Return auxiliary metadata for troubleshooting and UI context."""
        device, router = self._find_device_global()
        target = self._target
        target_type = target.tracker_type if target else TrackerTargetType.MAC
        target_source = target.source.value if target else None
        mapped_mac = target.mac if target else self._fallback_mac

        signal_dbm = device.signal_dbm if device else None
        noise_dbm = device.noise_dbm if device else None
        return {
            "router": router or self._host,
            "entity_key": self._entity_key,
            "tracker_type": target_type.value,
            "target_source": target_source,
            "mapped_mac": mapped_mac,
            "mapping_exists": target is not None,
            "ssid": device.ssid if device else None,
            "ap_device": device.ap_device if device else None,
            "signal_dbm": signal_dbm,
            "signal_average_dbm": device.signal_average_dbm if device else None,
            "noise_dbm": noise_dbm,
            "snr_db": signal_dbm - noise_dbm if signal_dbm is not None and noise_dbm is not None else None,
            "inactive_ms": device.inactive_ms if device else None,
            "connected_time_seconds": device.connected_time_seconds if device else None,
            "rx_rate_mbps": device.rx_rate_mbps if device else None,
            "tx_rate_mbps": device.tx_rate_mbps if device else None,
        }
