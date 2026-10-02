# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np
import pytest

from mynaphone.takes import TakeMeta, judge, longest_hole_ms, trim


def tone(seconds: float, rate: int = 48000, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    x = (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    return np.stack([x, x], axis=1)


def silence(seconds: float, rate: int = 48000) -> np.ndarray:
    return np.zeros((int(seconds * rate), 2), dtype=np.float32)


def test_trim_removes_leading_silence_and_truncates_to_duration():
    rate = 48000
    audio = np.concatenate([silence(1.0, rate), tone(10.0, rate), silence(2.0, rate)])
    out, lead_ms = trim(audio, rate, expected_ms=10_000, lead_window_s=2.0, tolerance_s=1.5)
    assert 990 <= lead_ms <= 1010
    # truncated to expected + 0.3 s, then trailing silence stripped back to expected
    assert abs(len(out) / rate - 10.0) < 0.05


def test_trim_keeps_trailing_silence_inside_published_length():
    rate = 48000
    audio = np.concatenate([tone(8.0, rate), silence(2.0, rate), silence(1.0, rate)])
    out, _ = trim(audio, rate, expected_ms=10_000, lead_window_s=2.0, tolerance_s=1.5)
    assert abs(len(out) / rate - 10.0) < 0.05        # the 2 s of silence inside the song stay


def test_trim_handles_empty_audio():
    out, lead = trim(np.zeros((0, 2), np.float32), 48000, 10_000, 2.0, 1.5)
    assert len(out) == 0 and lead == 0


def meta(expected_s: float = 240.0) -> TakeMeta:
    return TakeMeta(app="Spotify.exe", artist="A", title="T", expected_ms=int(expected_s * 1000))


def test_judge_keeps_a_clean_take(tmp_config):
    v = judge(meta(240), captured_s=240.2, wall_s=240.6, flags={"start_position_ms": 300}, cfg=tmp_config)
    assert v.keep and v.reasons == []


@pytest.mark.parametrize("flags,expected_reason", [
    ({"paused": True}, "paused"),
    ({"seek": True}, "seek"),
    ({"buffering": True}, "buffering"),
    ({"overflows": 2}, "capture_overflow:2"),
    ({"device_changes": 1}, "device_changed"),
    ({"start_position_ms": 5000}, "started_mid_track:5000ms"),
    ({"ended_early": "stopped"}, "stopped"),
    ({"mixer_volume": 30}, "mixer_volume:30"),
    ({"app_volume": 0}, "app_volume:0"),
])
def test_judge_discards_on_flags(tmp_config, flags, expected_reason):
    v = judge(meta(240), 240.0, 240.0, flags, tmp_config)
    assert not v.keep
    assert expected_reason in v.reasons


def test_judge_length_and_wall_clock_rules(tmp_config):
    assert any(r.startswith("length_mismatch") for r in judge(meta(240), 230.0, 240.0, {}, tmp_config).reasons)
    assert any(r.startswith("stalled") for r in judge(meta(240), 240.0, 250.0, {}, tmp_config).reasons)
    assert any(r.startswith("cut_short") for r in judge(meta(240), 240.0, 230.0, {}, tmp_config).reasons)


def test_judge_too_short_and_no_duration(tmp_config):
    assert "too_short" in judge(meta(20), 20.0, 20.0, {}, tmp_config).reasons
    assert "no_duration" in judge(meta(0), 100.0, 100.0, {}, tmp_config).reasons


def test_foreign_audio_discards_only_when_not_isolated(tmp_config):
    fa = {"apps": ["powershell.exe"], "count": 3, "max_db": -20.0}
    v = judge(meta(240), 240.0, 240.0, {"foreign_audio": dict(fa, isolated=False)}, tmp_config)
    assert "foreign_audio:powershell.exe" in v.reasons
    v2 = judge(meta(240), 240.0, 240.0, {"foreign_audio": dict(fa, isolated=True)}, tmp_config)
    assert v2.keep


def test_foreign_audio_rule_can_be_switched_off(tmp_config):
    tmp_config.rules.discard_on_foreign_audio = False
    fa = {"apps": ["chrome.exe"], "count": 1, "max_db": -30.0, "isolated": False}
    assert judge(meta(240), 240.0, 240.0, {"foreign_audio": fa}, tmp_config).keep


def test_longest_hole_leaves_out_silence_before_the_music_and_at_its_end():
    rate = 48000
    audio = np.concatenate([silence(1.5, rate), tone(30.0, rate), silence(4.0, rate)])
    assert longest_hole_ms(audio, rate) == 0
    assert longest_hole_ms(silence(5.0, rate), rate) == 0
    assert longest_hole_ms(np.zeros((0, 2), np.float32), rate) == 0


def test_longest_hole_finds_a_pause_inside_the_music():
    rate = 48000
    audio = np.concatenate([tone(20.0, rate), silence(1.2, rate), tone(20.0, rate)])
    assert 1150 <= longest_hole_ms(audio, rate) <= 1250


def test_a_stall_spoils_a_take_only_when_it_left_a_hole(tmp_config):
    """Per-app capture gets no sound while Spotify loads, so a stalled song usually comes out whole."""
    late = 240.0 + tmp_config.rules.duration_tolerance_seconds + 1.5
    whole = judge(meta(240), 240.0, late, {"buffering": True, "hole_ms": 20}, tmp_config)
    assert whole.keep and whole.reasons == []
    holed = judge(meta(240), 240.0, late, {"buffering": True, "hole_ms": 1200}, tmp_config)
    assert "buffering" in holed.reasons and any(r.startswith("stalled") for r in holed.reasons)
