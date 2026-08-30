"""Router health sensors for OpenWrt Ubus WiFi Presence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from custom_components.openwrt_ubus.const import CONF_HOST, DOMAIN
from custom_components.openwrt_ubus.data import OpenWrtUbusWifiPresenceConfigEntry, WifiPresenceDevice
from custom_components.openwrt_ubus.entity import OpenWrtUbusWifiPresenceEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo


@dataclass(frozen=True, kw_only=True)
class OpenWrtUbusRouterSensorDescription(SensorEntityDescription):
    """Describe one router-level WiFi metric."""

    value_fn: Callable[[dict[str, WifiPresenceDevice]], int | float | None]


def _signals(devices: dict[str, WifiPresenceDevice]) -> list[int]:
    """Return valid station signal readings."""
    return [device.signal_dbm for device in devices.values() if device.signal_dbm is not None]


def _average_signal(devices: dict[str, WifiPresenceDevice]) -> float | None:
    """Return the average station signal, when at least one reading exists."""
    signals = _signals(devices)
    return round(sum(signals) / len(signals), 1) if signals else None


def _weakest_signal(devices: dict[str, WifiPresenceDevice]) -> int | None:
    """Return the weakest station signal, when at least one reading exists."""
    signals = _signals(devices)
    return min(signals) if signals else None


ROUTER_SENSOR_DESCRIPTIONS: tuple[OpenWrtUbusRouterSensorDescription, ...] = (
    OpenWrtUbusRouterSensorDescription(
        key="associated_clients",
        translation_key="associated_clients",
        icon="mdi:wifi-marker",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=len,
    ),
    OpenWrtUbusRouterSensorDescription(
        key="average_station_signal",
        translation_key="average_station_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_average_signal,
    ),
    OpenWrtUbusRouterSensorDescription(
        key="weakest_station_signal",
        translation_key="weakest_station_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_weakest_signal,
    ),
)


class OpenWrtUbusRouterSensor(SensorEntity, OpenWrtUbusWifiPresenceEntity):
    """Expose one coordinator-level router health metric."""

    entity_description: OpenWrtUbusRouterSensorDescription

    def __init__(
        self,
        entry: OpenWrtUbusWifiPresenceConfigEntry,
        description: OpenWrtUbusRouterSensorDescription,
    ) -> None:
        """Initialize a router metric sensor."""
        coordinator = entry.runtime_data.coordinator
        super().__init__(coordinator)
        self.entity_description = description
        self._host = entry.data[CONF_HOST]
        self._attr_unique_id = f"{self._host}_{description.key}"
        self._attr_suggested_object_id = f"{self._host}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Group metrics under one router device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._host)},
            manufacturer="OpenWrt",
            model="WiFi access point",
            name=self._host,
        )

    @property
    def native_value(self) -> int | float | None:
        """Return the current metric value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        """Expose the currently observed AP interfaces and SSIDs."""
        return {
            "ap_devices": sorted({device.ap_device for device in self.coordinator.data.values()}),
            "ssids": sorted({device.ssid for device in self.coordinator.data.values() if device.ssid}),
        }
