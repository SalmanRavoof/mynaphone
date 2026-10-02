# Copyright (C) 2026 Salman Ravoof
# SPDX-License-Identifier: GPL-3.0-or-later
import datetime as dt

from mynaphone.config import Config
from mynaphone.store import Store, local_time, norm, tier_rank


def test_norm_strips_feat_and_brackets():
    assert norm("Neethanae (From \"Mersal\")") == "neethanae"
    assert norm("Song Title feat. Someone") == "song title"
    assert norm("A.R. Rahman") == "a r rahman"


def test_tier_rank_orders_quality_tiers():
    assert tier_rank("hifi") > tier_rank("very_high") > tier_rank("high") > tier_rank("youtube") > tier_rank("low")
    assert tier_rank(None) == 0 and tier_rank("weird") == 0


def test_store_dedup_by_uri_and_by_title(tmp_config):
    st = Store(tmp_config.paths.db_path)
    st.add_track(artist="A. R. Rahman", title="Neethanae (From \"Mersal\")", album="Mersal", duration_ms=269_000,
                 source_uri="spotify:track:x", quality_tier="high", file_path="p", state="library")
    assert st.find_archived("whoever", "whatever", 1, uri="spotify:track:x") is not None
    assert st.find_archived("A.R. Rahman", "Neethanae", 270_000) is not None     # normalised title, ±2 s
    assert st.find_archived("A.R. Rahman", "Neethanae", 280_000) is None         # too different in length
    assert st.find_archived("Someone Else", "Neethanae", 269_000) is None


def test_store_picks_best_tier_among_duplicates(tmp_config):
    st = Store(tmp_config.paths.db_path)
    st.add_track(artist="X", title="Y", duration_ms=100_000, quality_tier="high", file_path="a", state="library")
    st.add_track(artist="X", title="Y", duration_ms=100_000, quality_tier="very_high", file_path="b", state="library")
    assert st.find_archived("X", "Y", 100_000)["quality_tier"] == "very_high"


def test_store_migrates_columns_and_summarises(tmp_config):
    st = Store(tmp_config.paths.db_path)
    cols = {r[1] for r in st.conn.execute("PRAGMA table_info(tracks)")}
    assert {"missing_json", "manual_json", "identity_json", "lyrics_state", "last_lookup"} <= cols
    st.log_take(verdict="keep", reasons=[], artist="a", title="b")
    st.log_take(verdict="discard", reasons=["paused"], artist="a", title="c")
    s = st.summary()
    assert s["takes_kept"] == 1 and s["takes_discarded"] == 1


def test_config_roundtrip(tmp_config, tmp_path):
    c = tmp_config
    c.capture.bit_depth = 24
    c.rules.harvest_mode = True
    c.rules.sources = ["Spotify.exe"]
    c.identify.acoustid_key = "abc"
    c.library.format = "flac"
    out = tmp_path / "saved.toml"
    c.save(out)
    c2 = Config.load(out)
    assert c2.capture.bit_depth == 24
    assert c2.rules.harvest_mode is True
    assert c2.rules.sources == ["Spotify.exe"]
    assert c2.identify.acoustid_key == "abc"
    assert c2.library.format == "flac"
    assert c2.paths.inbox_dir == c.paths.inbox_dir


def test_config_relative_paths_resolve_next_to_file(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[paths]\ninbox_dir = "in"\n', encoding="utf-8")
    c = Config.load(p)
    assert c.paths.inbox_dir == (tmp_path / "in").resolve()
    assert c.paths.inbox_dir.exists()


def test_rules_matching():
    from mynaphone.config import Rules
    r = Rules(sources=["Spotify.exe", "chrome.exe"], ignore_titles=["Advertisement"])
    assert r.is_source("Spotify.exe") and r.is_source("spotify.exe") and r.is_source("C:\\x\\chrome.exe")
    assert not r.is_source("vlc.exe")
    assert r.is_ignored_title("advertisement") and r.is_ignored_title("") and not r.is_ignored_title("Song")


def test_take_times_show_in_local_time():
    stamp = "2026-10-02T08:07:31.180621+00:00"   # how the recorder stores started_at, in UTC
    utc_minus_6 = dt.timezone(dt.timedelta(hours=-6))
    assert local_time(stamp, tz=utc_minus_6) == "02:07"
    assert local_time(stamp, "%Y-%m-%d %H:%M:%S", tz=utc_minus_6) == "2026-10-02 02:07:31"
    assert local_time(None) == "" and local_time("not a time") == ""
