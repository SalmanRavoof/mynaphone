// Copyright (C) 2026 Salman Ravoof
// SPDX-License-Identifier: GPL-3.0-or-later
// mynaphone bridge: streams Spotify's own player state to the local mynaphone recorder.
// Sends exact track uri, duration, position, paused/buffering flags and the playback quality tier
// over a WebSocket to ws://127.0.0.1:8765. Reconnects automatically; harmless when mynaphone is off.
// It also answers the app's commands: list your playlists, read one's songs, play it from a song,
// pause, and look up track details for songs recorded earlier.
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
  // The authorization state holds the token Spotify keeps refreshed, the one Spicetify's own requests use.
  // The session's copy is the token from start-up: an hour later every request with it fails with 401.
  function accessTokens() {
    const out = [];
    try { const t = Spicetify.Platform.AuthorizationAPI.getState().token.accessToken; if (t) out.push(t); } catch (e) {}
    try { const t = Spicetify.Platform.Session.accessToken; if (t && !out.includes(t)) out.push(t); } catch (e) {}
    return out;
  }
  // The metadata service answers JSON when asked, but through CosmosAsync the Accept header is often
  // lost and the reply is protobuf. Fetch it with the client's token and read either form.
  function clientHeaders(token) {
    const h = { Authorization: "Bearer " + token, Accept: "application/json" };
    try { h["Spotify-App-Version"] = Spicetify.Platform.version; } catch (e) {}
    try { h["App-Platform"] = Spicetify.Platform.PlatformData.app_platform; } catch (e) {}
    return h;
  }
  async function getWithToken(url, label) {
    const tokens = accessTokens();
    if (!tokens.length) throw new Error(label + ": no access token");
    let r;
    for (const token of tokens) {
      r = await fetch(url, { headers: clientHeaders(token) });
      if (r.status !== 401) break;
    }
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
    const r = await getWithToken(
      "https://spclient.wg.spotify.com/metadata/4/album/" + idToHex(id) + "?market=from_token", "metadata service");
    const a = r.json;
    if (!a || a.error || !a.name) throw new Error("metadata service: " + (r.json ? errorText(a) : "protobuf reply"));
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

  // Spotify builds an ad as { type: "ad", uri: "spotify:ad:..." }; some builds flag it in the metadata instead
  function isAd(it) {
    const md = (it && it.metadata) || {};
    return !!it && (it.type === "ad" || it.provider === "ad" || (it.uri || "").startsWith("spotify:ad:")
      || md.is_advertisement === "true" || !!md.ad_id);
  }

  // Spicetify copies the state of a player object it finds in Spotify's code into Spicetify.Player.data. After
  // some starts it finds one that never changes, and its copy stays empty while songs play (October 3 and 30,
  // 2026). Spotify's own PlayerAPI always has the song, so the state comes from there, the same object the
  // playlist commands use, and Spicetify's copy only stands in when that can't be read.
  function playerState() {
    try {
      const api = Spicetify.Platform.PlayerAPI;
      const st = api.getState ? api.getState() : api._state;
      if (st && st.item) return st;
    } catch (e) {}
    const d = Spicetify.Player.data;
    return d && d.item ? d : null;
  }
  // the position as of the state's timestamp, brought up to now, as Spicetify.Player.getProgress() works it out
  function progress(d) {
    const at = Number(d.positionAsOfTimestamp), ts = Number(d.timestamp);
    if (!Number.isFinite(at)) return Spicetify.Player.getProgress();
    const p = d.isPaused || !Number.isFinite(ts) ? at : at + (Date.now() - ts);
    return Math.max(0, d.duration ? Math.min(p, d.duration) : p);
  }

  function snapshot() {
    const d = playerState();
    if (!d) return null;
    const it = d.item;
    const md = it.metadata || {};
    let position = 0;
    try { position = progress(d); } catch (e) {}
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
      next: (d.nextItems || []).slice(0, 3).map(n => ({ uri: n.uri, uid: n.uid, name: n.name })),
      isAd: isAd(it),
      context: (d.context && d.context.uri) || "",
      uid: it.uid || "",
      provider: it.provider || (md.provider || ""),
      // so the app's log can say when Spicetify's copy of the player is empty
      spicetifyEmpty: !(Spicetify.Player.data && Spicetify.Player.data.item),
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
  function sendState(force) {
    if (!ws || ws.readyState !== 1) return;
    const s = snapshot();
    if (!s) return;
    const albumUri = s.album && s.album.uri;
    if (albumUri && albumUri.startsWith("spotify:album:")) {
      s.albumInfo = details(albumUri, albumCache, [albumFromSpclient, albumFromGraphql, albumFromWebApi]);
    }
    if (s.uri && s.uri.startsWith("spotify:track:")) {
      s.trackInfo = details(s.uri, trackCache, [trackFromSpclient, trackFromWebApi]);
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

  // -- commands from the app --------------------------------------------------------------

  function names(artists) {
    return (artists || []).map(a => a.name || (a.profile && a.profile.name) || "").filter(Boolean);
  }
  function playlistTrack(x, index) {
    return {
      index: index, uri: x.uri || "", uid: x.uid || "", name: x.name || "", artists: names(x.artists),
      album: x.album ? { name: x.album.name || "", uri: x.album.uri || "" } : null,
      duration_ms: (x.duration && x.duration.milliseconds) || 0,
      playable: x.isPlayable !== false && !x.isLocal, local: !!x.isLocal, episode: x.type === "episode",
    };
  }
  async function listPlaylists() {
    const root = await Spicetify.Platform.RootlistAPI.getContents();
    const out = [];
    const walk = (node, folder) => {
      for (const it of (node && node.items) || []) {
        if (it.type === "folder") walk(it, it.name || folder);
        else if (it.type === "playlist") {
          out.push({ uri: it.uri, name: it.name || "", total: it.totalLength || 0, own: !!it.isOwnedBySelf,
                     owner: (it.owner && (it.owner.displayName || it.owner.username)) || "", folder: folder || "" });
        }
      }
    };
    walk(root, "");
    let liked = null;
    try {
      const lib = Spicetify.Platform.LibraryAPI;
      const t = await lib.getTracks({ offset: 0, limit: 0 });
      liked = { uri: lib._likedSongsUri || "spotify:collection:tracks", name: "Liked Songs",
                total: (t && t.totalLength) || 0, own: true, owner: "", folder: "" };
    } catch (e) {}
    return { playlists: out, liked: liked };
  }
  async function contextTracks(uri) {
    const out = [];
    if (uri.includes(":album:")) {
      const q = Spicetify.GraphQL.Definitions.queryAlbumTracks;
      for (let offset = 0; offset < 2000; offset += 100) {
        const r = await Spicetify.GraphQL.Request(q, { uri: uri, offset: offset, limit: 100 });
        const page = r && r.data && r.data.albumUnion && r.data.albumUnion.tracksV2;
        const items = (page && page.items) || [];
        for (const x of items) {
          const t = x.track || {};
          out.push({
            index: out.length, uri: t.uri || "", uid: x.uid || "", name: t.name || "",
            artists: names(t.artists && t.artists.items), album: { name: "", uri: uri },
            duration_ms: (t.duration && t.duration.totalMilliseconds) || 0,
            playable: !(t.playability && t.playability.playable === false), local: false, episode: false,
          });
        }
        if (items.length < 100 || (page && out.length >= page.totalCount)) break;
      }
      return out;
    }
    const liked = !uri.includes(":playlist:");
    for (let offset = 0; offset < 20000; offset += 500) {
      const r = liked ? await Spicetify.Platform.LibraryAPI.getTracks({ offset: offset, limit: 500 })
                      : await Spicetify.Platform.PlaylistAPI.getContents(uri, { offset: offset, limit: 500 });
      const items = (r && r.items) || [];
      for (const x of items) out.push(playlistTrack(x, out.length));
      // the reply's own offset is always 0, so pages are counted here
      if (items.length < 500 || out.length >= ((r && r.totalLength) || 0)) break;
    }
    return out;
  }
  function waitFor(test, ms) {
    return new Promise(resolve => {
      const started = Date.now();
      const tick = () => {
        let ok = false;
        try { ok = test(); } catch (e) {}
        if (ok || Date.now() - started > ms) resolve(ok);
        else setTimeout(tick, 250);
      };
      tick();
    });
  }
  async function play(cmd) {
    const P = Spicetify.Platform.PlayerAPI;
    const devices = Spicetify.Platform.ConnectDevicesAPI;
    const active = devices && devices.getActiveDevice ? devices.getActiveDevice() : null;
    if (active && active.isLocal === false) throw new Error("Spotify is playing on another device");
    const SH = Spicetify.Platform.ShuffleAPI;
    let shuffleWas = null;
    // for playlists, play() takes the shuffle mode saved for the playlist, so that one is turned off first
    try { if (SH && SH.getShuffle) shuffleWas = await SH.getShuffle(cmd.context); } catch (e) {}
    try { if (SH && SH.setShuffle) await SH.setShuffle(cmd.context, 0); } catch (e) {}
    const feature = cmd.context.includes(":album:") ? "album" : cmd.context.includes(":playlist:") ? "playlist"
      : "your_library";
    const skipTo = cmd.uid ? { uri: cmd.uri, uid: cmd.uid } : (cmd.uri ? { uri: cmd.uri } : { index: cmd.index || 0 });
    await P.play({ uri: cmd.context }, { featureIdentifier: feature }, { skipTo: skipTo, shuffle: false, repeat: 0 });
    const started = await waitFor(() => {
      const st = P.getState();
      return st && st.item && (!cmd.uri || st.item.uri === cmd.uri) && st.context && st.context.uri === cmd.context;
    }, 10000);
    try {
      const st = P.getState();
      if (st && (st.shuffle || st.smartShuffle)) await P.setShuffle(false);
      if (st && st.repeat) await P.setRepeat(0);
    } catch (e) {}
    if (!started) throw new Error("Spotify didn't start the song within 10 seconds");
    return { started: true, shuffle_was: shuffleWas };
  }
  async function restoreShuffle(cmd) {
    const SH = Spicetify.Platform.ShuffleAPI;
    if (SH && SH.setShuffle && cmd.mode !== null && cmd.mode !== undefined) await SH.setShuffle(cmd.context, cmd.mode);
    return {};
  }
  async function pause() {
    await Spicetify.Platform.PlayerAPI.pause();
    return {};
  }
  // details for songs recorded before the bridge could read them, one a second
  async function trackDetails(cmd) {
    let n = 0;
    for (const uri of cmd.uris || []) {
      if (!uri.startsWith("spotify:track:")) continue;
      let msg;
      try { msg = { type: "track_details", uri: uri, info: await trackFromSpclient(uri.split(":")[2]) }; }
      catch (e) { msg = { type: "track_details", uri: uri, error: describe(e) }; }
      if (!ws || ws.readyState !== 1) break;
      try { ws.send(JSON.stringify(msg)); } catch (e) {}
      n++;
      await new Promise(r => setTimeout(r, 1000));
    }
    return { done: n };
  }
  const COMMANDS = { playlists: listPlaylists, tracks: cmd => contextTracks(cmd.uri).then(t => ({ tracks: t })),
                     play: play, pause: pause, restore_shuffle: restoreShuffle, track_details: trackDetails };
  async function onCommand(cmd) {
    const reply = { type: "reply", id: cmd.id };
    try {
      const fn = COMMANDS[cmd.do];
      if (!fn) throw new Error("no command " + cmd.do);
      reply.ok = true;
      reply.result = await fn(cmd);
    } catch (e) {
      reply.ok = false;
      reply.error = describe(e);
    }
    if (ws && ws.readyState === 1) {
      try { ws.send(JSON.stringify(reply)); } catch (e) {}
    }
  }

  function connect() {
    try {
      ws = new WebSocket("ws://127.0.0.1:" + PORT + "/spotify");
    } catch (e) {
      setTimeout(connect, 5000);
      return;
    }
    ws.onopen = () => send(true);
    ws.onmessage = ev => {
      let msg = null;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg && msg.type === "command") onCommand(msg);
    };
    ws.onclose = () => { ws = null; setTimeout(connect, 5000); };
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  }

  connect();
  Spicetify.Player.addEventListener("songchange", () => send(true));
  Spicetify.Player.addEventListener("onplaypause", () => send(true));
  // Spicetify's events come from its copy, which can stay empty, so Spotify's own player says when songs change too
  try { Spicetify.Platform.PlayerAPI._events.addListener("update", () => send(true)); } catch (e) {}
  setInterval(() => send(false), 1000);
})();
