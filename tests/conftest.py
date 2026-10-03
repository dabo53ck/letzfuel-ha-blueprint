"""Drive the blueprint through the real Home Assistant automation engine.

The LëtzFuel HA integration is not installed: its sensors are plain states,
its events are fired on the bus, and every service the blueprint calls is a
recording mock. A test reads like an evening: set states, fire an event,
assert on the calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

BLUEPRINT_PATH = (
    Path(__file__).resolve().parent.parent
    / "blueprints/automation/dabo53ck/letzfuel_ha_blueprint.yaml"
)
BLUEPRINT_RELATIVE = "dabo53ck/letzfuel_ha_blueprint.yaml"

AUTOMATION_ALIAS = "Fuel blueprint"
AUTOMATION_KEY = "fuel_blueprint"

RECOMMENDATION = "sensor.letzfuel_ha_refuel_recommendation"
DIESEL = "sensor.letzfuel_ha_diesel_price"
SP95 = "sensor.letzfuel_ha_sp95_e10_price"
PERSON = "person.alex"
CAR_MOVING = "binary_sensor.car_moving"
LEVEL = "sensor.car_fuel_level"
DONE = "input_boolean.refuelled_today"

ANNOUNCED = "letzfuel_ha_price_change_announced"
CORRECTED = "letzfuel_ha_price_change_corrected"
CHANGED = "letzfuel_ha_price_changed"


async def settle(hass: HomeAssistant) -> None:
    """Let the automation run as far as it can.

    A reminder waits for its buttons until midnight, so
    ``async_block_till_done`` would never return while one is open. Counted in
    loop turns, not seconds: some tests freeze the clock.
    """
    task = asyncio.ensure_future(hass.async_block_till_done())
    for _ in range(1000):
        if task.done():
            return
        await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


class Calls:
    """Everything the blueprint asked Home Assistant to do."""

    def __init__(self) -> None:
        self.phones: dict[str, list[ServiceCall]] = {}
        self.custom: list[ServiceCall] = []
        self.helper_on: list[ServiceCall] = []
        self.helper_off: list[ServiceCall] = []

    @property
    def notify(self) -> list[ServiceCall]:
        """Notifications that reached the default phone."""
        return self.phones.get("phone", [])


class Fuel:
    """The integration as the automation sees it."""

    def __init__(self, hass: HomeAssistant, calls: Calls) -> None:
        self.hass = hass
        self.calls = calls

    async def state(
        self, entity_id: str, value: str, attributes: dict[str, Any] | None = None
    ) -> None:
        self.hass.states.async_set(entity_id, value, attributes)
        await settle(self.hass)

    async def recommend(self, value: str) -> None:
        await self.state(RECOMMENDATION, value, REC_ATTRIBUTES)

    async def press(self, action: str) -> None:
        """Tap a notification button."""
        self.hass.bus.async_fire("mobile_app_notification_action", {"action": action})
        await settle(self.hass)

    async def event(self, event_type: str, *changes: dict[str, Any]) -> None:
        self.hass.bus.async_fire(
            event_type, {"provider": "petrol.lu", "changes": list(changes)}
        )
        await settle(self.hass)

    def add_phone(self, name: str) -> str:
        """Register a Companion app device and return its device id.

        The app names its notify entity after the device (`notify.<name>`) and
        the legacy service `notify.mobile_app_<name>`.
        """
        entry = MockConfigEntry(domain="mobile_app", title=name)
        entry.add_to_hass(self.hass)
        device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={("mobile_app", name)},
            name=name,
        )
        er.async_get(self.hass).async_get_or_create(
            "notify",
            "mobile_app",
            f"{name}-notify",
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=name,
        )
        self.calls.phones[name] = async_mock_service(
            self.hass, "notify", f"mobile_app_{name}"
        )
        return device.id


REC_ATTRIBUTES = {
    "primary_fuel": "diesel",
    "today_price": 2.057,
    "tomorrow_price": 2.1,
    "delta": 0.043,
    "potential_saving_full_tank": 2.71,
}


def announced(fuel: str, current: float, upcoming: float) -> dict[str, Any]:
    delta = round(upcoming - current, 3)
    return {
        "fuel": fuel,
        "current_price": current,
        "upcoming_price": upcoming,
        "delta": delta,
        "direction": "up" if delta > 0 else "down",
        "effective_date": "2026-10-02",
    }


@pytest.fixture
def calls(hass: HomeAssistant) -> Calls:
    recorded = Calls()
    recorded.custom = async_mock_service(hass, "test", "custom")
    recorded.helper_on = async_mock_service(hass, "input_boolean", "turn_on")
    recorded.helper_off = async_mock_service(hass, "input_boolean", "turn_off")
    return recorded


@pytest.fixture
def fuel(hass: HomeAssistant, calls: Calls) -> Fuel:
    return Fuel(hass, calls)


@pytest.fixture
async def setup_blueprint(hass: HomeAssistant, tmp_path: Path, fuel: Fuel):
    """Install the blueprint and create one automation from it.

    Unless a test passes its own ``reminder_devices``, the reminder goes to one
    phone, ``phone``, whose notifications end up in ``calls.notify``.
    """

    async def _setup(**inputs: Any) -> None:
        target = tmp_path / "blueprints/automation" / BLUEPRINT_RELATIVE
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(BLUEPRINT_PATH, target)
        hass.config.config_dir = str(tmp_path)

        if "reminder_devices" not in inputs:
            inputs["reminder_devices"] = [fuel.add_phone("phone")]

        hass.states.async_set(RECOMMENDATION, "awaiting_price", REC_ATTRIBUTES)
        hass.states.async_set(DIESEL, "2.057", {"friendly_name": "Diesel price"})
        hass.states.async_set(SP95, "1.837", {"friendly_name": "SP95 price"})
        hass.states.async_set(PERSON, "home")
        hass.states.async_set("zone.home", "1", {"friendly_name": "Home"})
        hass.states.async_set("zone.work", "0", {"friendly_name": "Work"})
        hass.states.async_set(CAR_MOVING, "off")
        hass.states.async_set(LEVEL, "30")
        hass.states.async_set(DONE, "off")

        assert await async_setup_component(
            hass,
            "automation",
            {
                "automation": {
                    "alias": AUTOMATION_ALIAS,
                    "use_blueprint": {"path": BLUEPRINT_RELATIVE, "input": inputs},
                }
            },
        )
        await hass.async_block_till_done()

    return _setup
