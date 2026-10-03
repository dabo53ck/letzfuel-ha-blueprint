"""Behaviour of the blueprint, one scenario per test."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .conftest import (
    ANNOUNCED,
    AUTOMATION_KEY,
    BLUEPRINT_PATH,
    CAR_MOVING,
    CHANGED,
    CORRECTED,
    DIESEL,
    DONE,
    LEVEL,
    PERSON,
    RECOMMENDATION,
    Fuel,
    announced,
    settle,
)

CUSTOM = [
    {
        "action": "test.custom",
        "data": {
            "type": "{{ notification_type }}",
            "title": "{{ title }}",
            "message": "{{ message }}",
        },
    }
]

LEAVE_HOME = {"reminder_trackers": [PERSON], "reminder_zones": ["zone.home"]}


async def test_home_assistant_accepts_the_blueprint(
    hass: HomeAssistant, setup_blueprint: Any
) -> None:
    await setup_blueprint()

    assert hass.states.get(f"automation.{AUTOMATION_KEY}").state == "on"


def test_declared_minimum_version() -> None:
    metadata = load_yaml(str(BLUEPRINT_PATH))["blueprint"]
    assert metadata["homeassistant"]["min_version"] == "2026.7.0"


async def test_nothing_is_enabled_by_default(setup_blueprint: Any, fuel: Fuel) -> None:
    await setup_blueprint(**LEAVE_HOME)
    await fuel.recommend("refuel_today")

    await fuel.state(PERSON, "not_home")
    await fuel.event(ANNOUNCED, announced("diesel", 2.057, 2.1))

    assert fuel.calls.notify == []
    assert fuel.calls.custom == []


async def test_manual_run_does_nothing_and_logs_no_error(
    hass: HomeAssistant, setup_blueprint: Any, fuel: Fuel, caplog: Any
) -> None:
    await setup_blueprint(
        reminder_enabled=True,
        threshold_below=2.0,
        threshold_actions=CUSTOM,
        rec_actions=CUSTOM,
        **LEAVE_HOME,
    )
    await fuel.recommend("refuel_today")
    fuel.calls.custom.clear()

    await hass.services.async_call(
        "automation",
        "trigger",
        {"entity_id": f"automation.{AUTOMATION_KEY}"},
        blocking=True,
    )
    await settle(hass)

    assert fuel.calls.notify == []
    assert fuel.calls.custom == []
    assert "UndefinedError" not in caplog.text
    assert "Error" not in caplog.text


class TestReminder:
    async def test_leaving_a_place(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(reminder_enabled=True, **LEAVE_HOME)
        await fuel.recommend("refuel_today")

        await fuel.state(PERSON, "not_home")

        assert len(fuel.calls.notify) == 1
        data = fuel.calls.notify[0].data
        assert data["title"] == "Refuel today"
        assert data["message"].split("\n") == [
            "DIESEL: 2.057 €/L today, 2.100 €/L tomorrow (+4.3 ct/L)",
            "A full tank saves about 2.71 €",
        ]
        assert data["data"]["tag"] == "letzfuel_reminder"
        assert data["data"]["entity_id"] == RECOMMENDATION
        titles = [button["title"] for button in data["data"]["actions"]]
        assert titles == ["Refuelled", "Later"]

    async def test_other_places_and_moves_inside_do_not_count(
        self, setup_blueprint: Any, fuel: Fuel
    ) -> None:
        await setup_blueprint(
            reminder_enabled=True,
            reminder_trackers=[PERSON],
            reminder_zones=["zone.work"],
        )
        await fuel.recommend("refuel_today")

        await fuel.state(PERSON, "not_home")
        assert fuel.calls.notify == []

        await fuel.state(PERSON, "Work")
        await fuel.state(PERSON, "not_home")
        assert len(fuel.calls.notify) == 1

    async def test_only_while_refuel_today(
        self, setup_blueprint: Any, fuel: Fuel
    ) -> None:
        await setup_blueprint(reminder_enabled=True, **LEAVE_HOME)
        await fuel.recommend("wait")

        await fuel.state(PERSON, "not_home")

        assert fuel.calls.notify == []

    async def test_car_starts_moving(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(reminder_enabled=True, reminder_moving=[CAR_MOVING])
        await fuel.recommend("refuel_today")

        await fuel.state(CAR_MOVING, "on")

        assert len(fuel.calls.notify) == 1

    @pytest.mark.parametrize("expected_lingering_timers", [True])
    async def test_at_a_set_time(
        self, hass: HomeAssistant, setup_blueprint: Any, fuel: Fuel, freezer: Any
    ) -> None:
        at = (dt_util.now() + timedelta(minutes=2)).replace(second=0, microsecond=0)
        await setup_blueprint(
            reminder_enabled=True, reminder_times=f"06:00, {at.strftime('%H:%M')}"
        )
        await fuel.recommend("refuel_today")

        freezer.move_to(at)
        async_fire_time_changed(hass, at)
        await settle(hass)

        assert len(fuel.calls.notify) == 1

    async def test_not_when_the_tank_is_full_enough(
        self, setup_blueprint: Any, fuel: Fuel
    ) -> None:
        await setup_blueprint(
            reminder_enabled=True,
            reminder_level_entity=LEVEL,
            reminder_level_below=50,
            **LEAVE_HOME,
        )
        await fuel.recommend("refuel_today")
        await fuel.state(LEVEL, "80")

        await fuel.state(PERSON, "not_home")

        assert fuel.calls.notify == []

    async def test_refuelled_button(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(
            reminder_enabled=True, reminder_done_helper=DONE, **LEAVE_HOME
        )
        await fuel.recommend("refuel_today")
        await fuel.state(PERSON, "not_home")

        done = fuel.calls.notify[0].data["data"]["actions"][0]["action"]
        await fuel.press(done)

        assert [call.data["entity_id"] for call in fuel.calls.helper_on] == [[DONE]]
        assert fuel.calls.notify[-1].data["message"] == "clear_notification"

    async def test_no_reminder_once_refuelled(
        self, setup_blueprint: Any, fuel: Fuel
    ) -> None:
        await setup_blueprint(
            reminder_enabled=True, reminder_done_helper=DONE, **LEAVE_HOME
        )
        await fuel.recommend("refuel_today")
        await fuel.state(DONE, "on")

        await fuel.state(PERSON, "not_home")

        assert fuel.calls.notify == []

    async def test_helper_resets_when_refuel_today_starts(
        self, setup_blueprint: Any, fuel: Fuel
    ) -> None:
        await setup_blueprint(reminder_enabled=True, reminder_done_helper=DONE)

        await fuel.recommend("refuel_today")

        assert [call.data["entity_id"] for call in fuel.calls.helper_off] == [[DONE]]

    @pytest.mark.parametrize("expected_lingering_timers", [True])
    async def test_later_button(
        self, hass: HomeAssistant, setup_blueprint: Any, fuel: Fuel, freezer: Any
    ) -> None:
        await setup_blueprint(
            reminder_enabled=True, reminder_snooze_minutes=30, **LEAVE_HOME
        )
        await fuel.recommend("refuel_today")
        await fuel.state(PERSON, "not_home")

        later = fuel.calls.notify[0].data["data"]["actions"][1]["action"]
        await fuel.press(later)
        assert len(fuel.calls.notify) == 1

        freezer.tick(timedelta(minutes=31))
        async_fire_time_changed(hass)
        await settle(hass)

        assert len(fuel.calls.notify) == 2
        assert fuel.calls.notify[1].data["title"] == "Refuel today"

    async def test_reminder_goes_when_refuel_today_ends(
        self, setup_blueprint: Any, fuel: Fuel
    ) -> None:
        await setup_blueprint(reminder_enabled=True, **LEAVE_HOME)
        await fuel.recommend("refuel_today")

        await fuel.recommend("awaiting_price")

        assert fuel.calls.notify[-1].data["message"] == "clear_notification"
        assert fuel.calls.notify[-1].data["data"]["tag"] == "letzfuel_reminder"

    async def test_german_and_own_message(
        self, setup_blueprint: Any, fuel: Fuel
    ) -> None:
        await setup_blueprint(
            reminder_enabled=True,
            notify_language="de",
            reminder_message="Noch {saving} € sparen: {fuel} {today} statt {tomorrow}",
            **LEAVE_HOME,
        )
        await fuel.recommend("refuel_today")

        await fuel.state(PERSON, "not_home")

        data = fuel.calls.notify[0].data
        assert data["title"] == "Heute tanken"
        assert data["message"] == "Noch 2,71 € sparen: DIESEL 2,057 statt 2,100"
        titles = [button["title"] for button in data["data"]["actions"]]
        assert titles == ["Getankt", "Später"]

    async def test_no_device_no_waiting(
        self, hass: HomeAssistant, setup_blueprint: Any, fuel: Fuel
    ) -> None:
        await setup_blueprint(
            reminder_enabled=True,
            reminder_devices=[],
            reminder_actions=CUSTOM,
            **LEAVE_HOME,
        )
        await fuel.recommend("refuel_today")

        await fuel.state(PERSON, "not_home")

        assert fuel.calls.custom[0].data["type"] == "reminder"
        state = hass.states.get(f"automation.{AUTOMATION_KEY}")
        assert state.attributes["current"] == 0

    async def test_own_actions(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(
            reminder_enabled=True, reminder_actions=CUSTOM, **LEAVE_HOME
        )
        await fuel.recommend("refuel_today")

        await fuel.state(PERSON, "not_home")

        assert fuel.calls.custom[0].data["type"] == "reminder"
        assert fuel.calls.custom[0].data["title"] == "Refuel today"


class TestNavigate:
    async def test_nearby(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(
            reminder_enabled=True,
            reminder_snooze_minutes=0,
            nav_mode="nearby",
            nav_app="google",
            **LEAVE_HOME,
        )
        await fuel.recommend("refuel_today")

        await fuel.state(PERSON, "not_home")

        actions = fuel.calls.notify[0].data["data"]["actions"]
        assert [button["title"] for button in actions] == ["Refuelled", "Navigate"]
        assert actions[1]["action"] == "URI"
        assert actions[1]["uri"] == (
            "https://www.google.com/maps/search/?api=1&query=petrol%20station"
        )

    async def test_my_station(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(
            reminder_enabled=True,
            nav_mode="place",
            nav_place={"latitude": 49.61, "longitude": 6.13},
            nav_app="apple",
            **LEAVE_HOME,
        )
        await fuel.recommend("refuel_today")

        await fuel.state(PERSON, "not_home")

        actions = fuel.calls.notify[0].data["data"]["actions"]
        assert actions[2]["uri"] == "https://maps.apple.com/?dirflg=d&daddr=49.61,6.13"


class TestOwnActions:
    async def test_announced(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(announced_actions=CUSTOM)

        await fuel.event(
            ANNOUNCED,
            announced("diesel", 2.057, 2.019),
            announced("sp95", 1.793, 1.837),
        )

        assert fuel.calls.custom[0].data == {
            "type": "announced",
            "title": "Price change tomorrow",
            "message": "DIESEL: -3.8 ct/L → 2.019 €/L (02/10/2026)",
        }

    async def test_fuels_and_minimum_change(
        self, setup_blueprint: Any, fuel: Fuel
    ) -> None:
        await setup_blueprint(
            announced_actions=CUSTOM,
            events_fuels=["diesel", "sp95"],
            events_min_delta=0.03,
        )

        await fuel.event(
            ANNOUNCED,
            announced("diesel", 2.057, 2.07),
            announced("sp95", 1.793, 1.837),
        )

        assert fuel.calls.custom[0].data["message"] == (
            "SP95: +4.4 ct/L → 1.837 €/L (02/10/2026)"
        )

    async def test_nothing_left_nothing_runs(
        self, setup_blueprint: Any, fuel: Fuel
    ) -> None:
        await setup_blueprint(announced_actions=CUSTOM)

        await fuel.event(ANNOUNCED, announced("sp95", 1.793, 1.837))

        assert fuel.calls.custom == []

    async def test_corrected(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(announced_actions=CUSTOM)

        await fuel.event(
            CORRECTED,
            {
                "fuel": "diesel",
                "effective_date": "2026-09-26",
                "announced_price": 2.055,
                "corrected_price": 2.095,
                "current_price": 2.095,
                "delta": 0.0,
                "direction": "none",
            },
        )

        assert fuel.calls.custom[0].data == {
            "type": "corrected",
            "title": "Correction: announced price",
            "message": (
                "DIESEL: 2.095 €/L (no change) instead of 2.055 €/L (26/09/2026)"
            ),
        }

    async def test_effective(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(effective_actions=CUSTOM, events_fuels=["sp95"])

        await fuel.event(
            CHANGED,
            {
                "fuel": "sp95",
                "old_price": 1.793,
                "new_price": 1.837,
                "effective_date": "2026-10-02",
            },
        )

        assert fuel.calls.custom[0].data == {
            "type": "effective",
            "title": "New fuel price in effect",
            "message": "SP95: 1.837 €/L (+4.4 ct/L)",
        }

    async def test_recommendation(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(
            rec_actions=CUSTOM,
            rec_states=["refuel_today", "wait"],
            notify_language="lb",
        )

        await fuel.recommend("wait")
        await fuel.recommend("refuel_today")

        assert [call.data for call in fuel.calls.custom] == [
            {
                "type": "recommendation",
                "title": "Tankempfeelung",
                "message": "Waarden\nMuer voll tanke spuert ongeféier 2,71 €",
            },
            {
                "type": "recommendation",
                "title": "Tankempfeelung",
                "message": "Haut tanken\nVoll tanke spuert ongeféier 2,71 €",
            },
        ]

    async def test_threshold(self, setup_blueprint: Any, fuel: Fuel) -> None:
        await setup_blueprint(threshold_actions=CUSTOM, threshold_below=2.0)

        await fuel.state(DIESEL, "1.95", {"friendly_name": "Diesel price"})

        assert fuel.calls.custom[0].data == {
            "type": "threshold",
            "title": "Price below your target",
            "message": "Diesel is at 1.950 €/L (target: below 2.000)",
        }
