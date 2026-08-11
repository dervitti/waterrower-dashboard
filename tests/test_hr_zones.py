from app.hr_zones import age_from_birth_year, estimate_max_hr, zone_for_hr, zone_bounds


def test_estimate_max_hr_male():
    hr = estimate_max_hr(sex="m", age=40, weight_kg=80)
    # 210 - 0.5*40 - 0.05*80 + 4 = 210 - 20 - 4 + 4 = 190
    assert hr == 190


def test_estimate_max_hr_female():
    hr = estimate_max_hr(sex="f", age=40, weight_kg=65)
    # 210 - 20 - 3.25 = 186.75 → 187
    assert hr == 187


def test_age_from_birth_year():
    from datetime import date

    assert age_from_birth_year(1990, today=date(2026, 1, 1)) == 36


def test_zones_and_lookup():
    zones = zone_bounds(200)
    assert len(zones) == 5
    assert zones[0]["name"] == "Gesundheits-Zone"
    assert zones[-1]["name"] == "Wettkampf-Zone"
    z = zone_for_hr(185, 200)
    assert z is not None
    assert z["key"] == "race"
