# Testing

Three layers. The first two run in CI; the third is a manual test on a real
instance.

## 1. Static checks

```bash
pip install pyyaml yamllint
yamllint -c .yamllint.yml blueprints tests/fixtures .github
python scripts/validate_blueprints.py
```

`validate_blueprints.py` checks the metadata, that every `!input` is declared and
every input used, that tuning inputs have defaults, that `source_url` points at
this file, that links to blueprint files in the README and docs exist, and that
the blueprint version matches the newest CHANGELOG section.

CI also lets Home Assistant itself build the automation from
`tests/fixtures/check_config/automations.yaml`, which sets every input, with
`check_config` on the declared minimum (2026.7) and the latest Home Assistant.

## 2. Behaviour tests

`tests/` runs the blueprint through the real Home Assistant automation engine.
The integration's sensors are plain states, its events are fired on the bus and
every service the blueprint calls is a recording mock.

```bash
pip install -r requirements-test.txt
pytest
```

Home Assistant does not run on native Windows. Use Linux, macOS, WSL or a
container; CI runs on Ubuntu.

## 3. Live test

Import the blueprint from `main` (or from a branch through its blob URL) on a
Home Assistant with LëtzFuel HA and create an automation.

- **Own actions:** wait for an announcement, or fire the events by hand in
  Developer tools → Events (`letzfuel_ha_price_change_announced` with a
  `changes` list, see the integration's README for the payload).
- **Reminder:** set `sensor.letzfuel_ha_refuel_recommendation` to
  `refuel_today` in Developer tools → States (with the attributes
  `primary_fuel`, `today_price`, `tomorrow_price`, `potential_saving_full_tank`),
  then trigger an occasion, for example a time a minute ahead. Reloading the
  integration restores the real state.
