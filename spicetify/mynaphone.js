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

  // Track and album details come from Spotify's internal metadata service first (the same kind of
  // endpoint as the lyrics), then for albums from the album page's GraphQL query, and last from the
  // public web API, which often refuses the client's own token.
  // Only answers are cached; a failure is reported to the app and retried after RETRY_MS.
  const RETRY_MS = 10 * 60 * 1000;
  const failed = new Map();     // uri -> { error, until }
  const inFlight = new Map();   // uri -> promise
  const B62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
  function idToHex(id) {
    let n = 0n;
    for (const c of id) n = n * 62n + BigInt(B62.indexOf(c));
    return n.toString(16).padStart(32, "0");
  }
  // readable, one-line text for a failed request or a thrown error, without binary from the reply
  function clean(text) {
    return String(text).replace(/[^\x20-\x7e]/g, "?").replace(/\s+/g, " ").trim().slice(0, 160);
  }
  function errorText(r) {
    if (!r) return "empty reply";
    const e = r.error;
    return clean(typeof e === "object" ? (e.status || "") + " " + (e.message || "") : e);
  }
  function describe(e) {
    if (e === undefined || e === null || e === "") return "no error text";
    if (typeof e !== "object") return clean(e);
    const parts = [e.name, e.status, e.code, e.message].filter(x => x !== undefined && x !== null && x !== "");
    if (!parts.length) {
      try { parts.push(JSON.stringify(e)); } catch (x) { parts.push(Object.prototype.toString.call(e)); }
    }
    return clean(parts.join(" "));
  }
  const JSON_HEADERS = { Accept: "application/json" };
  function accessToken() {
    try { const t = Spicetify.Platform.Session.accessToken; if (t) return t; } catch (e) {}
    try { return Spicetify.Platform.AuthorizationAPI.getState().token.accessToken || ""; } catch (e) {}
    return "";
  }
  // The metadata service answers JSON when asked, but through CosmosAsync the Accept header is often
  // lost and the reply is protobuf. Fetch it with the client's token and read either form.
  async function getWithToken(url, label) {
    const token = accessToken();
    if (!token) throw new Error(label + ": no access token");
    const r = await fetch(url, { headers: { Authorization: "Bearer " + token, Accept: "application/json" } });
    if (!r.ok) throw new Error(label + ": HTTP " + r.status);
    if ((r.headers.get("content-type") || "").includes("json")) return { json: await r.json() };
    return { bytes: new Uint8Array(await r.arrayBuffer()) };
  }
  // just enough protobuf to read Spotify's Track message: field number -> list of raw values
  function protoFields(buf) {
    const out = new Map();
    let i = 0;
    const varint = () => {
      let n = 0n, shift = 0n, b;
      do {
        if (i >= buf.length) throw new Error("truncated protobuf");
        b = buf[i++];
        n |= BigInt(b & 0x7f) << shift;
        shift += 7n;
      } while (b & 0x80);
      return n;
    };
    while (i < buf.length) {
      const key = Number(varint());
      const field = key >> 3, wire = key & 7;
      let v = null;
      if (wire === 0) v = varint();
      else if (wire === 2) { const len = Number(varint()); v = buf.subarray(i, i + len); i += len; }
      else if (wire === 1) i += 8;
      else if (wire === 5) i += 4;
      else throw new Error("protobuf wire type " + wire);
      if (i > buf.length) throw new Error("truncated protobuf");
      if (!out.has(field)) out.set(field, []);
      out.get(field).push(v);
    }
    return out;
  }
  const utf8 = b => new TextDecoder().decode(b);
  const zigzag = n => (n === undefined ? undefined : Number((n >> 1n) ^ -(n & 1n)));
  // Track: 2 name, 5 number, 6 disc_number, 7 duration, 8 popularity (sint32), 9 explicit,
  // 10 external_id { 1 type, 2 id }
  function trackFromProto(buf) {
    const f = protoFields(buf);
    const one = k => (f.get(k) || [])[0];
    if (one(2) === undefined) throw new Error("metadata service: no track in the reply");
    let isrc;
    for (const raw of f.get(10) || []) {
      const e = protoFields(raw);
      const type = e.has(1) ? utf8(e.get(1)[0]) : "";
      if (type.toLowerCase() === "isrc" && e.has(2)) isrc = utf8(e.get(2)[0]);
    }
    return {
      isrc: isrc, explicit: one(9) === undefined ? undefined : one(9) === 1n, popularity: zigzag(one(8)),
      track_number: zigzag(one(5)), disc_number: zigzag(one(6)), duration_ms: zigzag(one(7)),
      source: "spclient protobuf",
    };
  }
  function trackFromJson(t) {
    if (!t || t.error || !t.name) throw new Error("metadata service: " + errorText(t));
    const isrc = (t.external_id || []).find(x => (x.type || "").toLowerCase() === "isrc");
    return {
      isrc: isrc ? isrc.id : undefined, explicit: t.explicit, popularity: t.popularity,
      track_number: t.number, disc_number: t.disc_number, duration_ms: t.duration, source: "spclient",
    };
  }
  function isoDate(d) {
    if (!d || !d.year) return { date: "", precision: "" };
    const p2 = n => String(n).padStart(2, "0");
    if (!d.month) return { date: String(d.year), precision: "year" };
    if (!d.day) return { date: d.year + "-" + p2(d.month), precision: "month" };
    return { date: d.year + "-" + p2(d.month) + "-" + p2(d.day), precision: "day" };
  }
  async function trackFromSpclient(id) {
    const r = await getWithToken(
      "https://spclient.wg.spotify.com/metadata/4/track/" + idToHex(id) + "?market=from_token", "metadata service");
    return r.json ? trackFromJson(r.json) : trackFromProto(r.bytes);
  }
  // the old route, kept in case the client's fetch is refused: answers JSON now and then
  async function trackFromCosmos(id) {
    return trackFromJson(await Spicetify.CosmosAsync.get(
      "https://spclient.wg.spotify.com/metadata/4/track/" + idToHex(id) + "?market=from_token", undefined,
      JSON_HEADERS));
  }
  async function trackFromWebApi(id) {
    const t = (await getWithToken("https://api.spotify.com/v1/tracks/" + id, "web API")).json;
    if (!t || t.error || !t.id) throw new Error("web API: " + errorText(t));
    return {
      isrc: t.external_ids && t.external_ids.isrc, explicit: t.explicit, popularity: t.popularity,
      track_number: t.track_number, disc_number: t.disc_number, duration_ms: t.duration_ms,
      track_total: t.album && t.album.total_tracks, source: "web API",
    };
  }
  async function albumFromSpclient(id) {
    const a = await Spicetify.CosmosAsync.get(
      "https://spclient.wg.spotify.com/metadata/4/album/" + idToHex(id) + "?market=from_token", undefined,
      JSON_HEADERS);
    if (!a || a.error || !a.name) throw new Error("metadata service: " + errorText(a));
    const d = isoDate(a.date);
    return {
      release_date: d.date, release_date_precision: d.precision,
      album_type: (a.type || "").toLowerCase(), label: a.label,
      total_tracks: (a.disc || []).reduce((n, disc) => n + (disc.track || []).length, 0) || undefined,
      copyrights: (a.copyright || []).map(c => c.text).filter(Boolean).slice(0, 2),
      artists: (a.artist || []).map(x => x.name), source: "spclient",
    };
  }
  // the album page's own query; field names have changed between Spotify versions, so both are read
  async function albumFromGraphql(id) {
    const q = Spicetify.GraphQL && Spicetify.GraphQL.Definitions && Spicetify.GraphQL.Definitions.getAlbum;
    if (!q) throw new Error("GraphQL: no getAlbum query in this Spotify version");
    let locale = "";
    try { locale = Spicetify.Locale.getLocale(); } catch (e) {}
    const r = await Spicetify.GraphQL.Request(q, { uri: "spotify:album:" + id, locale: locale, offset: 0, limit: 50 });
    const a = r && r.data && r.data.albumUnion;
    if (!a || !a.name) throw new Error("GraphQL: " + clean(JSON.stringify((r && r.errors) || r || {})));
    const iso = (a.date && a.date.isoString) || "";
    const precision = ((a.date && a.date.precision) || "").toLowerCase();
    const tracks = a.tracksV2 || a.tracks || {};
    return {
      release_date: iso.slice(0, precision === "year" ? 4 : precision === "month" ? 7 : 10),
      release_date_precision: precision, album_type: (a.type || "").toLowerCase(), label: a.label,
      total_tracks: tracks.totalCount,
      copyrights: ((a.copyright && a.copyright.items) || []).map(c => c.text).slice(0, 2),
      artists: ((a.artists && a.artists.items) || []).map(x => x.profile && x.profile.name).filter(Boolean),
      source: "GraphQL",
    };
  }
  async function albumFromWebApi(id) {
    const a = await Spicetify.CosmosAsync.get("https://api.spotify.com/v1/albums/" + id);
    if (!a || a.error || !a.id) throw new Error("web API: " + errorText(a));
    return {
      release_date: a.release_date, release_date_precision: a.release_date_precision,
      album_type: a.album_type, total_tracks: a.total_tracks, label: a.label,
      copyrights: (a.copyrights || []).map(c => c.text).slice(0, 2),
      artists: (a.artists || []).map(x => x.name), source: "web API",
    };
  }
  // the details for a uri, or { error } after both sources failed; null while a lookup is running
  function details(uri, cache, sources) {
    if (cache.has(uri)) return cache.get(uri);
    const f = failed.get(uri);
    if (f && Date.now() < f.until) return { error: f.error };
    if (!inFlight.has(uri)) {
      const id = uri.split(":")[2];
      inFlight.set(uri, (async () => {
        const errors = [];
        for (const source of sources) {
          try {
            const info = await source(id);
            cache.set(uri, info);
            if (cache.size > 300) cache.delete(cache.keys().next().value);
            failed.delete(uri);
            return;
          } catch (e) { errors.push(describe(e)); }
        }
        failed.set(uri, { error: errors.join("; "), until: Date.now() + RETRY_MS });
      })().finally(() => { inFlight.delete(uri); send(true); }));
    }
    return null;
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

  // a failure inside send() used to vanish; report it to the app, at most once a minute
  let lastErrorAt = 0;
  function report(where, e) {
    if (!ws || ws.readyState !== 1 || Date.now() - lastErrorAt < 60000) return;
    lastErrorAt = Date.now();
    try { ws.send(JSON.stringify({ type: "error", where: where, error: describe(e) })); } catch (x) {}
  }
  function send(force) {
    try { sendState(force); } catch (e) { report("send", e); }
  }
  // After a fresh start the extension once saw no track for 20 minutes while songs played. Say so when
  // Spicetify.Player has nothing but Spotify's own player API has a track.
  let noTrackSince = 0, stuckReported = false;
  function playerApiHasTrack() {
    try {
      const api = Spicetify.Platform.PlayerAPI;
      const st = api.getState ? api.getState() : api._state;
      return !!(st && st.item);
    } catch (e) { return false; }
  }
  function sendState(force) {
    if (!ws || ws.readyState !== 1) return;
    const s = snapshot();
    if (!s) {
      noTrackSince = noTrackSince || Date.now();
      if (!stuckReported && Date.now() - noTrackSince > 60000 && playerApiHasTrack()) {
        stuckReported = true;
        report("snapshot", "Spicetify.Player has had no track for a minute, but PlayerAPI has one");
      }
      return;
    }
    noTrackSince = 0;
    const albumUri = s.album && s.album.uri;
    if (albumUri && albumUri.startsWith("spotify:album:")) {
      s.albumInfo = details(albumUri, albumCache, [albumFromSpclient, albumFromGraphql, albumFromWebApi]);
    }
    if (s.uri && s.uri.startsWith("spotify:track:")) {
      s.trackInfo = details(s.uri, trackCache, [trackFromSpclient, trackFromCosmos, trackFromWebApi]);
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
    try { ws.send(JSON.stringify(s)); } catch (e) { report("sending state", e); }
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
