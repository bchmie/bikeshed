"""Seam B: the wear engine as pure input/output pairs.

Expected values are worked examples taken from the spec and the validated
prototype, not recomputations of the implementation.
"""

from __future__ import annotations

from datetime import date

from app.wear import (
    DUE,
    OK,
    RETIRED,
    WARN,
    EventInput,
    InstallationInput,
    PartInput,
    RideInput,
    attribute_ride,
    evaluate,
    needs_attention,
)

TODAY = date(2025, 11, 20)


# --- builders ---------------------------------------------------------------


def part(
    *,
    id=1,
    name="Chain #3",
    part_type="chain",
    wear_unit="km",
    threshold=300,
    trainer=True,
    wet=True,
    measurement=None,
    attached_chain=None,
):
    return PartInput(
        id=id,
        name=name,
        part_type=part_type,
        wear_unit=wear_unit,
        threshold=threshold,
        wears_on_trainer=trainer,
        wears_when_wet=wet,
        measurement_threshold=measurement,
        attached_chain_id=attached_chain,
    )


def install(part_id=1, bike_id=1, start=date(2025, 9, 1), end=None, initial=0.0):
    return InstallationInput(
        part_id=part_id,
        bike_id=bike_id,
        installed_on=start,
        removed_on=end,
        initial_km=initial,
    )


def ride(id=1, on=date(2025, 11, 1), km=100.0, bike=1, trainer=False, wet=False):
    return RideInput(
        id=id,
        occurred_on=on,
        distance_km=km,
        bike_id=bike,
        trainer=trainer,
        wet=wet,
    )


def event(id=1, part_id=1, kind="wax", on=date(2025, 11, 1), **kwargs):
    return EventInput(id=id, part_id=part_id, kind=kind, occurred_on=on, **kwargs)


def state(parts, installations, rides=(), events=(), today=TODAY):
    return evaluate(parts, installations, rides, events, today)


# --- km wear and attribution ------------------------------------------------


def test_km_accrues_only_on_the_part_s_bike():
    result = state(
        [part()],
        [install()],
        [ride(1, km=150, bike=1), ride(2, km=150, bike=1), ride(3, km=999, bike=2)],
    )[1]
    assert result.level == DUE
    assert result.since_service_km == 300
    assert "300 km since last wax" in result.reason
    assert "limit 300 km" in result.reason


def test_km_below_the_interval_is_ok():
    result = state([part()], [install()], [ride(km=299)])[1]
    assert result.level == OK
    assert result.since_service_km == 299


def test_trainer_rides_wear_trainer_parts_but_not_tires():
    chain = part(id=1, trainer=True)
    tire = part(id=2, name="Front tire", part_type="tire", threshold=4000, trainer=False, wet=False)
    rides = [ride(1, km=40, trainer=True), ride(2, km=20, trainer=False)]
    result = state([chain, tire], [install(1), install(2)], rides)
    assert result[1].since_service_km == 60
    assert result[2].since_service_km == 20


# --- wet-ride invalidation --------------------------------------------------


def test_a_wet_ride_makes_a_wet_sensitive_part_due_immediately():
    result = state(
        [part()],
        [install()],
        [ride(1, on=date(2025, 11, 10), km=8, wet=True)],
    )[1]
    assert result.level == DUE
    assert result.wet_since_service is True
    assert result.last_wet_on == date(2025, 11, 10)
    assert "wet ride on 2025-11-10" in result.reason
    assert "invalidated" in result.reason


def test_a_wet_ride_does_not_make_a_non_wet_sensitive_part_due():
    tire = part(id=2, name="Front tire", part_type="tire", threshold=4000, trainer=False, wet=False)
    result = state([tire], [install(2)], [ride(km=10, wet=True)])[2]
    assert result.level == OK
    assert "wet" not in result.reason.lower()


def test_re_wax_after_a_wet_ride_clears_the_wet_due_state():
    events = [
        event(1, kind="wax", on=date(2025, 11, 1)),
        event(2, kind="wax", on=date(2025, 11, 12)),
    ]
    result = state([part()], [install()], [ride(on=date(2025, 11, 10), km=8, wet=True)], events)[1]
    assert result.level == OK
    assert result.wet_since_service is False


def test_a_wet_ride_before_the_last_wax_does_not_invalidate_the_clock():
    events = [event(1, kind="wax", on=date(2025, 11, 12))]
    result = state(
        [part()],
        [install()],
        [ride(1, on=date(2025, 11, 10), km=8, wet=True), ride(2, on=date(2025, 11, 13), km=5)],
        events,
    )[1]
    assert result.level == OK
    assert result.since_service_km == 5


# --- days-based wear --------------------------------------------------------


def test_days_threshold_crosses_the_due_line_on_the_interval_day():
    sealant = part(
        id=3,
        name="Sealant — front",
        part_type="sealant",
        wear_unit="days",
        threshold=45,
        trainer=False,
        wet=False,
    )
    top_up = event(
        1,
        part_id=3,
        kind="sealant",
        on=date(2025, 10, 1),
        product_interval_days=45,
        product_name="Orange Seal Regular",
    )
    just_before = state([sealant], [install(3)], [], [top_up], today=date(2025, 11, 14))[3]
    on_the_day = state([sealant], [install(3)], [], [top_up], today=date(2025, 11, 15))[3]
    assert just_before.level == OK
    assert on_the_day.level == DUE
    assert on_the_day.days_since_service == 45
    assert "45 days since the last top-up" in on_the_day.reason
    assert "Orange Seal Regular: 45-day interval" in on_the_day.reason


def test_switching_to_a_longer_lived_product_moves_the_due_date():
    sealant = part(
        id=3, part_type="sealant", wear_unit="days", threshold=45, trainer=False, wet=False
    )
    regular = event(
        1,
        part_id=3,
        kind="sealant",
        on=date(2025, 10, 1),
        product_interval_days=45,
        product_name="Orange Seal Regular",
    )
    endurance = event(
        2,
        part_id=3,
        kind="sealant",
        on=date(2025, 10, 1),
        product_interval_days=90,
        product_name="Orange Seal Endurance",
    )
    assert state([sealant], [install(3)], [], [regular])[3].level == DUE
    assert state([sealant], [install(3)], [], [endurance])[3].level == OK


def test_days_part_with_no_service_event_is_due_now():
    sealant = part(
        id=3, part_type="sealant", wear_unit="days", threshold=45, trainer=False, wet=False
    )
    result = state([sealant], [install(3)])[3]
    assert result.level == DUE
    assert "no sealant logged yet" in result.reason


# --- measurement thresholds -------------------------------------------------


def test_a_measurement_over_the_limit_outranks_the_odometer_and_a_wet_ride():
    chain = part(measurement=0.75)
    rides = [ride(km=10, wet=True)]
    readings = [
        event(1, kind="wax", on=date(2025, 11, 1)),
        event(2, kind="reading", on=date(2025, 11, 15), reading=0.85),
    ]
    result = state([chain], [install()], rides, readings)[1]
    assert result.level == DUE
    assert result.reading == 0.85
    assert "0.85% stretch" in result.reason
    assert "measurement outranks" in result.reason


def test_a_reading_below_the_limit_does_not_trigger_replacement():
    chain = part(measurement=0.75)
    result = state(
        [chain],
        [install()],
        [],
        [event(1, kind="reading", on=date(2025, 11, 15), reading=0.5)],
    )[1]
    assert result.level == OK


def test_re_wax_does_not_clear_a_stretch_reading():
    chain = part(measurement=0.75)
    readings = [
        event(1, kind="reading", on=date(2025, 11, 2), reading=0.85),
        event(2, kind="wax", on=date(2025, 11, 10)),
    ]
    result = state([chain], [install()], [], readings)[1]
    assert result.level == DUE
    assert result.reading == 0.85


# --- initial offsets and resets ---------------------------------------------


def test_initial_km_makes_the_service_clock_start_realistic():
    result = state([part()], [install(initial=3100)])[1]
    assert result.level == DUE
    assert result.since_service_km == 3100
    assert result.total_km == 3100
    assert "3,100 km" in result.reason


def test_a_wax_resets_the_clock_including_the_initial_offset():
    events = [event(1, kind="wax", on=date(2025, 9, 10))]
    result = state([part()], [install(initial=3100)], [], events)[1]
    assert result.level == OK
    assert result.since_service_km == 0
    assert result.total_km == 3100


# --- lifecycle / rotation ---------------------------------------------------


def test_install_windows_attribute_rides_to_the_right_part():
    chain_a = part(id=1, name="Chain A")
    chain_b = part(id=2, name="Chain B")
    installations = [
        install(1, start=date(2025, 9, 1), end=date(2025, 9, 30)),
        install(2, start=date(2025, 10, 1), end=date(2025, 10, 31)),
        install(1, start=date(2025, 11, 1)),
    ]
    rides = [
        ride(1, on=date(2025, 9, 10), km=100),
        ride(2, on=date(2025, 10, 10), km=100),
        ride(3, on=date(2025, 11, 10), km=100),
    ]
    result = state([chain_a, chain_b], installations, rides)
    assert result[1].total_km == 200
    assert result[1].since_service_km == 100
    assert result[2].total_km == 100
    assert result[2].bike_id == 1


def test_reinstall_can_carry_another_initial_offset():
    chain_a = part(id=1)
    installations = [
        install(1, start=date(2025, 9, 1), end=date(2025, 9, 30), initial=1000),
        install(1, start=date(2025, 11, 1), initial=50),
    ]
    rides = [ride(1, on=date(2025, 11, 10), km=100)]
    result = state([chain_a], installations, rides)[1]
    assert result.total_km == 1150
    assert result.since_service_km == 150


def test_a_part_can_move_between_bikes():
    chain = part(id=1)
    installations = [
        install(1, bike_id=1, start=date(2025, 9, 1), end=date(2025, 9, 30)),
        install(1, bike_id=2, start=date(2025, 10, 1)),
    ]
    rides = [
        ride(1, on=date(2025, 9, 10), km=50, bike=1),
        ride(2, on=date(2025, 10, 10), km=70, bike=2),
    ]
    result = state([chain], installations, rides)[1]
    assert result.bike_id == 2
    assert result.total_km == 120
    assert result.since_service_km == 70


def test_retired_parts_keep_their_lifetime_summary():
    chain = part(id=1)
    installations = [install(1, start=date(2025, 9, 1), end=date(2025, 10, 8))]
    rides = [ride(1, on=date(2025, 9, 10), km=4100)]
    result = state([chain], installations, rides)[1]
    assert result.level == RETIRED
    assert result.lifetime_km == 4100
    assert "Retired" in result.reason
    assert "4,100 km lifetime" in result.reason


def test_install_and_remove_dates_are_inclusive():
    chain = part(id=1)
    installations = [install(1, start=date(2025, 9, 1), end=date(2025, 9, 30))]
    rides = [
        ride(1, on=date(2025, 9, 1), km=10),
        ride(2, on=date(2025, 9, 30), km=20),
        ride(3, on=date(2025, 10, 1), km=99),
    ]
    result = state([chain], installations, rides)[1]
    assert result.lifetime_km == 30


# --- uses (quick link) ------------------------------------------------------


def test_waxes_on_the_attached_chain_are_counted_as_link_uses():
    link = part(
        id=9,
        name="Quick link",
        part_type="quicklink",
        wear_unit="uses",
        threshold=5,
        attached_chain=1,
    )
    chain = part(id=1)
    waxes = [
        event(1, part_id=1, kind="wax", on=date(2025, 9, 5)),
        event(2, part_id=1, kind="wax", on=date(2025, 9, 20)),
        event(3, part_id=1, kind="wax", on=date(2025, 10, 5)),
        event(4, part_id=1, kind="wax", on=date(2025, 10, 20)),
    ]
    result = state([chain, link], [install(1), install(9)], [], waxes)
    assert result[9].uses == 4
    assert result[9].level == WARN
    assert "4 of 5 open/close cycles" in result[9].reason


def test_a_link_reaches_its_limit_and_becomes_due():
    link = part(
        id=9,
        part_type="quicklink",
        wear_unit="uses",
        threshold=5,
        attached_chain=1,
    )
    waxes = [event(i, part_id=1, kind="wax", on=date(2025, 10, i)) for i in range(1, 6)]
    result = state([part(id=1), link], [install(1), install(9)], [], waxes)
    assert result[9].uses == 5
    assert result[9].level == DUE
    assert "5 of 5" in result[9].reason


def test_link_uses_can_be_adjusted_manually_and_are_counted_from_install():
    link = part(
        id=9,
        part_type="quicklink",
        wear_unit="uses",
        threshold=5,
        attached_chain=1,
    )
    events = [
        event(1, part_id=1, kind="wax", on=date(2025, 8, 1)),  # before the link was installed
        event(2, part_id=1, kind="wax", on=date(2025, 10, 5)),
        event(3, part_id=9, kind="uses_adjust", on=date(2025, 10, 10), uses_delta=2),
        event(4, part_id=9, kind="uses_adjust", on=date(2025, 10, 11), uses_delta=-1),
    ]
    result = state([part(id=1), link], [install(1), install(9)], [], events)
    assert result[9].uses == 2


def test_wet_rides_wear_unit_counts_wet_rides_only():
    part_ = part(
        id=4,
        name="Wet-ride counter",
        part_type="brake_pads",
        wear_unit="wet_rides",
        threshold=2,
        trainer=False,
        wet=True,
    )
    rides = [
        ride(1, wet=True, trainer=False),
        ride(2, wet=True, trainer=False),
        ride(3, wet=False, trainer=False),
    ]
    result = state([part_], [install(4)], rides)[4]
    assert result.level == DUE
    assert "2 wet rides" in result.reason


# --- attribution ------------------------------------------------------------


def test_trainer_rides_go_to_the_trainer_bike_without_a_guess_flag():
    attribution = attribute_ride(gear_bike_id=1, trainer=True, default_bike_id=1, trainer_bike_id=2)
    assert attribution.bike_id == 2
    assert attribution.needs_confirmation is False


def test_known_gear_wins_for_outdoor_rides():
    attribution = attribute_ride(
        gear_bike_id=2, trainer=False, default_bike_id=1, trainer_bike_id=3
    )
    assert attribution.bike_id == 2
    assert attribution.needs_confirmation is False


def test_unknown_bike_falls_back_to_the_default_and_is_flagged():
    attribution = attribute_ride(
        gear_bike_id=None, trainer=False, default_bike_id=1, trainer_bike_id=3
    )
    assert attribution.bike_id == 1
    assert attribution.needs_confirmation is True


# --- ordering ---------------------------------------------------------------


def test_needs_attention_puts_due_before_warn():
    chain = part(id=1)
    link = part(id=9, part_type="quicklink", wear_unit="uses", threshold=2, attached_chain=1)
    waxes = [event(1, part_id=1, kind="wax", on=date(2025, 10, 1))]
    status = state([chain, link], [install(1), install(9)], [ride(km=999, wet=True)], waxes)
    attention = needs_attention(status.values())
    assert [s.level for s in attention] == [DUE, WARN]
    assert attention[0].part_id == 1
