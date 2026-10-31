// Copyright (C) 2026 Salman Ravoof
// SPDX-License-Identifier: GPL-3.0-or-later
// Runs spicetify/mynaphone.js in Node against stand-ins for Spicetify, Spotify's player and the app's
// WebSocket, and checks the state it sends and the commands it answers. tests/test_spicetify_extension.py
// runs it: node tests/js/extension_harness.mjs spicetify/mynaphone.js
import fs from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const src = fs.readFileSync(process.argv[2], "utf8");
const wait = ms => new Promise(r => setTimeout(r, ms));

// Loads the extension once, with its own stand-ins, and returns what it sent and its socket.
async function load(Spicetify) {
  const sent = [];
  const out = { sent, socket: null, fetches: [] };
  class FakeWS {
    constructor(url) { this.url = url; this.readyState = 1; out.socket = this; setTimeout(() => this.onopen && this.onopen(), 0); }
    send(s) { sent.push(JSON.parse(s)); }
    close() {}
  }
  const ctx = {
    window: {}, Spicetify, WebSocket: FakeWS, TextDecoder, BigInt, console, Map, Set, Promise, JSON, Date, Math,
    Number, setTimeout: (f, ms) => setTimeout(f, Math.min(ms, 5)), setInterval: () => 0,
    fetch: async (url, opts) => { out.fetches.push([url, opts.headers]); return {
      status: 200, ok: true, headers: { get: () => "application/json" },
      json: async () => ({ name: "x", number: 3, disc_number: 1, duration: 200000,
                           external_id: [{ type: "isrc", id: "QMBZ1" }] }) }; },
  };
  ctx.window.Spicetify = Spicetify;
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  await wait(20);
  return out;
}

const platformBase = () => ({
  version: "1.2.93.666", PlatformData: { app_platform: "Win32" },
  AuthorizationAPI: { getState: () => ({ token: { accessToken: "tok" } }) },
});
const spicetifyBase = () => ({ CosmosAsync: { get: async () => ({}) }, GraphQL: { Definitions: {}, Request: async () => ({}) } });

// -- Spicetify's copy stays empty while Spotify plays (October 3 and 30, 2026) ----------------------------

{
  const listeners = [];
  const playing = {
    item: { uri: "spotify:track:kkkg", uid: "u1", provider: "context", name: "Kabhi Khushi Kabhie Gham",
            artists: [{ name: "Jatin-Lalit", uri: "spotify:artist:jl" }],
            album: { name: "Kabhi Khushi Kabhie Gham", uri: "spotify:album:k3g" }, metadata: {} },
    duration: 472000, isPaused: false, isBuffering: false, timestamp: Date.now() - 2000,
    positionAsOfTimestamp: 30000, context: { uri: "spotify:album:k3g" }, playbackId: "pb1",
    playbackQuality: { bitrateLevel: "HIGH" },
  };
  const Spicetify = {
    ...spicetifyBase(),
    Player: {
      addEventListener() {}, getVolume: () => 1, data: undefined,
      getProgress: () => { throw new Error("Spicetify's player object never changes"); },
    },
    Platform: {
      ...platformBase(),
      PlayerAPI: { getState: () => playing, _events: { addListener: (name, fn) => listeners.push([name, fn]) } },
    },
  };
  const { sent } = await load(Spicetify);
  const states = () => sent.filter(m => m.type === "state");
  const st = states()[0];
  assert.ok(st, "a state is sent while Spicetify's copy is empty");
  assert.equal(st.uri, "spotify:track:kkkg");
  assert.equal(st.spicetifyEmpty, true);
  assert.ok(st.position >= 32000 && st.position < 33000, "position brought up to now: " + st.position);
  assert.equal(st.isPaused, false);
  assert.equal(st.context, "spotify:album:k3g");
  // Spotify's player says when the song changes, since Spicetify's events come from its empty copy
  assert.ok(listeners.some(l => l[0] === "update"), "listens to Spotify's player");
  const n = states().length;
  playing.item = { ...playing.item, uri: "spotify:track:next", name: "Next" };
  listeners.find(l => l[0] === "update")[1]({ data: playing });
  await wait(10);
  const after = states().slice(n);          // and again once the new song's details arrive
  assert.ok(after.length >= 1 && after.every(s => s.uri === "spotify:track:next"), "the next song is sent at once");
  // paused: the position stays where the player left it
  playing.isPaused = true;
  listeners.find(l => l[0] === "update")[1]({ data: playing });
  await wait(10);
  assert.equal(states().at(-1).position, 30000);
}

// -- a healthy Spicetify, an ad playing, and the commands ----------------------------------------------

const playlistItems = Array.from({ length: 1203 }, (_, i) => ({
  type: i === 7 ? "episode" : "track", uri: `spotify:track:t${i}`, uid: `u${i}`, name: `Song ${i}`,
  artists: [{ name: "A", uri: "spotify:artist:a" }], album: { name: "Al", uri: "spotify:album:al" },
  duration: { milliseconds: 200000 + i }, isPlayable: i !== 3, isLocal: i === 5,
}));
let state = {
  item: { type: "ad", uri: "spotify:ad:123", name: "", metadata: { title: "Brand" }, provider: "ad" },
  duration: 30000, isPaused: false, isBuffering: false, context: { uri: "spotify:playlist:p" },
  timestamp: Date.now(), positionAsOfTimestamp: 1000, shuffle: true, repeat: 1,
};
const calls = [];
const Spicetify = {
  ...spicetifyBase(),
  Player: { addEventListener() {}, getProgress: () => 1000, getVolume: () => 1, data: state },
  Platform: {
    ...platformBase(),
    RootlistAPI: { getContents: async () => ({ type: "folder", items: [
      { type: "playlist", uri: "spotify:playlist:p", name: "Car", totalLength: 1203, isOwnedBySelf: true, owner: { displayName: "S" } },
      { type: "folder", name: "Films", items: [{ type: "playlist", uri: "spotify:playlist:q", name: "Leo", totalLength: 9 }] },
      { type: "placeholder", uri: "spotify:playlist:gone" }] }) },
    LibraryAPI: { _likedSongsUri: "spotify:user:s:collection", getTracks: async () => ({ totalLength: 412, items: [] }) },
    PlaylistAPI: { getContents: async (uri, { offset, limit }) => ({ offset: 0, totalLength: 1203, items: playlistItems.slice(offset, offset + limit) }) },
    ShuffleAPI: { getShuffle: async () => 1, setShuffle: async (ctx, mode) => calls.push(["setShuffle", ctx, mode]) },
    ConnectDevicesAPI: { getActiveDevice: () => ({ isLocal: true }) },
    PlayerAPI: {
      play: async (ctx, origin, opts) => { calls.push(["play", ctx.uri, origin.featureIdentifier, opts.skipTo]);
        state = { ...state, item: { uri: opts.skipTo.uri }, context: { uri: ctx.uri } }; },
      getState: () => state, setShuffle: async v => { calls.push(["P.setShuffle", v]); state.shuffle = v; },
      setRepeat: async v => { calls.push(["setRepeat", v]); state.repeat = v; },
      pause: async () => calls.push(["pause"]),
    },
  },
};
const { sent, socket, fetches } = await load(Spicetify);

// every state carries the ad flag, the context and the provider
const st = sent.find(m => m.type === "state");
assert.ok(st && st.isAd === true && st.context === "spotify:playlist:p" && st.provider === "ad", "ad state");
assert.equal(st.spicetifyEmpty, false);

async function command(cmd) {
  const n = sent.length;
  socket.onmessage({ data: JSON.stringify({ type: "command", ...cmd }) });
  for (let i = 0; i < 400; i++) {
    const r = sent.slice(n).find(m => m.type === "reply" && m.id === cmd.id);
    if (r) return r;
    await wait(5);
  }
  throw new Error("no reply to " + cmd.do);
}

let r = await command({ id: 1, do: "playlists" });
assert.ok(r.ok, r.error);
assert.equal(JSON.stringify(r.result.playlists.map(p => [p.name, p.folder])), JSON.stringify([["Car", ""], ["Leo", "Films"]]));
assert.equal(r.result.liked.uri, "spotify:user:s:collection");
assert.equal(r.result.liked.total, 412);

r = await command({ id: 2, do: "tracks", uri: "spotify:playlist:p" });
assert.ok(r.ok, r.error);
const t = r.result.tracks;
assert.equal(t.length, 1203, "every page read");
assert.equal(t[1202].uri, "spotify:track:t1202");
assert.equal(t[3].playable, false); assert.equal(t[5].local, true); assert.equal(t[7].episode, true);
assert.equal(t[9].duration_ms, 200009);

r = await command({ id: 3, do: "play", context: "spotify:playlist:p", uri: "spotify:track:t9", uid: "u9" });
assert.ok(r.ok, r.error);
assert.equal(r.result.shuffle_was, 1);
assert.equal(JSON.stringify(calls.find(c => c[0] === "play")), JSON.stringify(["play", "spotify:playlist:p", "playlist", { uri: "spotify:track:t9", uid: "u9" }]));
assert.ok(calls.some(c => c[0] === "setShuffle" && c[2] === 0), "the playlist's shuffle turned off first");
assert.ok(calls.some(c => c[0] === "P.setShuffle" && c[1] === false) && calls.some(c => c[0] === "setRepeat"));

Spicetify.Platform.ConnectDevicesAPI.getActiveDevice = () => ({ isLocal: false });
r = await command({ id: 4, do: "play", context: "spotify:playlist:p", uri: "spotify:track:t9" });
assert.equal(r.ok, false); assert.match(r.error, /another device/);

r = await command({ id: 5, do: "pause" });
assert.ok(r.ok && calls.some(c => c[0] === "pause"));

r = await command({ id: 6, do: "track_details", uris: ["spotify:track:6rqhFgbbKwnb9MLmUQDhG6", "spotify:episode:x"] });
assert.ok(r.ok, r.error);
assert.equal(r.result.done, 1);
const d = sent.find(m => m.type === "track_details");
assert.equal(d.info.isrc, "QMBZ1");
assert.ok(fetches.some(f => f[1]["Spotify-App-Version"] === "1.2.93.666"), "the client's own headers");

r = await command({ id: 7, do: "nonsense" });
assert.equal(r.ok, false);
console.log("extension: all checks passed");
process.exit(0);
