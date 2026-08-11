from app.ble.parser import parse_rower_data


def test_parse_basic_with_hr():
    # flags: stroke+count, distance, pace, power, energy, hr, elapsed
    # bit0=0 (stroke present), bit2 distance, bit3 pace, bit5 power, bit8 energy, bit9 hr, bit11 elapsed
    flags = 0x0000 | 0x0004 | 0x0008 | 0x0020 | 0x0100 | 0x0200 | 0x0800
    payload = bytearray()
    payload += flags.to_bytes(2, "little")
    payload += bytes([48])  # stroke rate 24.0 (48 * 0.5)
    payload += (12).to_bytes(2, "little")  # stroke count
    payload += (500).to_bytes(3, "little")  # distance
    payload += (120).to_bytes(2, "little")  # pace
    payload += (180).to_bytes(2, "little", signed=True)  # power
    payload += (45).to_bytes(2, "little")  # total energy
    payload += (500).to_bytes(2, "little")  # per hour
    payload += bytes([8])  # per minute
    payload += bytes([142])  # hr
    payload += (95).to_bytes(2, "little")  # elapsed

    parsed = parse_rower_data(payload)
    assert parsed.stroke_rate == 24.0
    assert parsed.stroke_count == 12
    assert parsed.distance_m == 500
    assert parsed.pace_s == 120
    assert parsed.power_w == 180
    assert parsed.total_energy_kcal == 45
    assert parsed.heart_rate == 142
    assert parsed.elapsed_s == 95
