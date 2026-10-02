// Copyright (C) 2026 Salman Ravoof
// SPDX-License-Identifier: GPL-3.0-or-later
// mynaphone bridge: streams Spotify's own player state to the local mynaphone recorder.
// Sends exact track uri, duration, position, paused/buffering flags and the playback quality tier
// over a WebSocket to ws://127.0.0.1:8765. Reconnects automatically; harmless when mynaphone is off.
(function mynaphone() {
  if (!window.Spicetify || !Spicetify.Player || !Spicetify.Player.addEventListener) {
    setTimeout(mynaphone, 500);
    return;
  }
  const PORT = 8765;
  let ws = null;
  let lastSent = "";
  // album details (release date, type, label) fetched with the client's own session, cached per album
  const albumCache = new Map();
  const trackCache = new Map();
  // Spotify's own lyrics (the microphone icon), line-synced, via the client's lyrics service
  const lyricsCache = new Map();
  async function lyricsFor(uri) {
    if (!uri || !uri.startsWith("spotify:track:")) return null;
    if (lyricsCache.has(uri)) return lyricsCache.get(uri);
    lyricsCache.set(uri, null);
    try {
      const id = uri.split(":")[2];
      const r = await Spicetify.CosmosAsync.get(
        "https://spclient.wg.spotify.com/color-lyrics/v2/track/" + id + "?format=json&vocalRemoval=false&market=from_token");
      const l = r && r.lyrics;
      if (!l || !l.lines || !l.lines.length) { lyricsCache.set(uri, { none: true }); return lyricsCache.get(uri); }
      const synced = l.syncType === "LINE_SYNCED";
      const lines = l.lines.map(x => ({ t: synced ? parseInt(x.startTimeMs || "0", 10) : null, w: x.words || "" }));
      const info = { synced: synced, language: l.language || "", provider: l.provider || "", lines: lines };
      lyricsCache.set(uri, info);
      if (lyricsCache.size > 200) lyricsCache.delete(lyricsCache.keys().next().value);
      return info;
    } catch (e) { lyricsCache.set(uri, { none: true }); return lyricsCache.get(uri); }
  }
  const lyricsSent = new Set();
  async function trackInfo(uri) {
    if (!uri || !uri.startsWith("spotify:track:")) return null;
    if (trackCache.has(uri)) return trackCache.get(uri);
    trackCache.set(uri, null);
    try {
      const id = uri.split(":")[2];
      const t = await Spicetify.CosmosAsync.get("https://api.spotify.com/v1/tracks/" + id);
      const info = t ? {
        isrc: t.external_ids && t.external_ids.isrc, explicit: t.explicit, popularity: t.popularity,
        track_number: t.track_number, disc_number: t.disc_number, duration_ms: t.duration_ms,
        track_total: t.album && t.album.total_tracks,
      } : null;
      trackCache.set(uri, info);
      if (trackCache.size > 300) trackCache.delete(trackCache.keys().next().value);
      return info;
    } catch (e) { return null; }
  }
  async function albumInfo(uri) {
    if (!uri || !uri.startsWith("spotify:album:")) return null;
    if (albumCache.has(uri)) return albumCache.get(uri);
    albumCache.set(uri, null);
    try {
      const id = uri.split(":")[2];
      const a = await Spicetify.CosmosAsync.get("https://api.spotify.com/v1/albums/" + id);
      const info = a ? {
        release_date: a.release_date, release_date_precision: a.release_date_precision,
        album_type: a.album_type, total_tracks: a.total_tracks, label: a.label,
        copyrights: (a.copyrights || []).map(c => c.text).slice(0, 2),
        artists: (a.artists || []).map(x => x.name),
      } : null;
      albumCache.set(uri, info);
      if (albumCache.size > 200) albumCache.delete(albumCache.keys().next().value);
      return info;
    } catch (e) { return null; }
  }

  function snapshot() {
    const d = Spicetify.Player.data;
    if (!d || !d.item) return null;
    const it = d.item;
    const md = it.metadata || {};
    let position = 0;
    try { position = Spicetify.Player.getProgress(); } catch (e) {}
    let volume = null;
    try { volume = Spicetify.Player.getVolume(); } catch (e) {}
    return {
      type: "state",
      ts: Date.now(),
      uri: it.uri || "",
      name: it.name || md.title || "",
      artists: (it.artists || []).map(a => ({ name: a.name, uri: a.uri })),
      album: it.album ? { name: it.album.name, uri: it.album.uri } : (md.album_title ? { name: md.album_title, uri: md.album_uri } : null),
      image: md.image_xlarge_url || md.image_large_url || (it.images && it.images.length ? it.images[it.images.length - 1].url : ""),
      duration: d.duration || (it.duration && it.duration.milliseconds) || 0,
      position: position,
      volume: volume,
      isPaused: !!d.isPaused,
      isBuffering: !!d.isBuffering,
      quality: d.playbackQuality || null,
      playbackId: d.playbackId || "",
      metadata: {
        album_track_number: md.album_track_number,
        album_disc_number: md.album_disc_number,
        album_track_count: md.album_track_count,
        album_disc_count: md.album_disc_count,
        artist_name: md.artist_name,
        album_artist_name: md.album_artist_name,
        popularity: md.popularity,
        is_explicit: md.is_explicit,
        is_local: md.is_local,
      },
      next: (d.nextItems || []).slice(0, 3).map(n => ({ uri: n.uri, name: n.name })),
      albumInfo: null,
      trackInfo: null,
    };
  }

  function send(force) {
    if (!ws || ws.readyState !== 1) return;
    const s = snapshot();
    if (!s) return;
    const albumUri = s.album && s.album.uri;
    if (albumUri && albumCache.has(albumUri)) {
      s.albumInfo = albumCache.get(albumUri);
    } else if (albumUri) {
      albumInfo(albumUri).then(() => send(true));
    }
    if (s.uri && trackCache.has(s.uri)) {
      s.trackInfo = trackCache.get(s.uri);
    } else if (s.uri) {
      trackInfo(s.uri).then(() => send(true));
    }
    // lyrics travel once per track, as their own message, since they are large
    if (s.uri && !lyricsSent.has(s.uri)) {
      lyricsSent.add(s.uri);
      if (lyricsSent.size > 500) lyricsSent.clear();
      lyricsFor(s.uri).then(info => {
        if (info && !info.none && ws && ws.readyState === 1) {
          try { ws.send(JSON.stringify({ type: "lyrics", uri: s.uri, lyrics: info })); } catch (e) {}
        }
      });
    }
    // every message carries position; only de-duplicate exact repeats
    const sig = JSON.stringify([s.uri, s.playbackId, s.isPaused, s.isBuffering, s.position]);
    if (!force && sig === lastSent) return;
    lastSent = sig;
    try { ws.send(JSON.stringify(s)); } catch (e) {}
  }

  function connect() {
    try {
      ws = new WebSocket("ws://127.0.0.1:" + PORT + "/spotify");
    } catch (e) {
      setTimeout(connect, 5000);
      return;
    }
    ws.onopen = () => send(true);
    ws.onclose = () => { ws = null; setTimeout(connect, 5000); };
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  }

  connect();
  Spicetify.Player.addEventListener("songchange", () => send(true));
  Spicetify.Player.addEventListener("onplaypause", () => send(true));
  setInterval(() => send(false), 1000);
})();
