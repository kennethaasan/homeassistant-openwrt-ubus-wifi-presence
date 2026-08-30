"""Router connectivity entity for OpenWrt Ubus WiFi Presence."""

from __future__ import annotations

from custom_components.openwrt_ubus.const import CONF_HOST, DOMAIN
from custom_components.openwrt_ubus.data import OpenWrtUbusWifiPresenceConfigEntry
from custom_components.openwrt_ubus.entity import OpenWrtUbusWifiPresenceEntity
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo


class OpenWrtUbusRouterConnectivityBinarySensor(BinarySensorEntity, OpenWrtUbusWifiPresenceEntity):
    """Report whether one OpenWrt coordinator is updating successfully."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "router_connectivity"

    def __init__(self, entry: OpenWrtUbusWifiPresenceConfigEntry) -> None:
        """Initialize one router connectivity entity."""
        coordinator = entry.runtime_data.coordinator
        super().__init__(coordinator)
        self._host = entry.data[CONF_HOST]
        self._attr_unique_id = f"{self._host}_connectivity"
        self._attr_suggested_object_id = f"{self._host}_connectivity"

    @property
    def available(self) -> bool:
        """Keep the entity available so failed updates render as disconnected."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the latest router update succeeded."""
        return self.coordinator.last_update_success

    @property
    def device_info(self) -> DeviceInfo:
        """Group metrics under one router device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._host)},
            manufacturer="OpenWrt",
            model="WiFi access point",
            name=self._host,
        )
