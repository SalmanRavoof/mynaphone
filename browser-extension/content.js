// Copyright (C) 2026 Salman Ravoof
// SPDX-License-Identifier: GPL-3.0-or-later
// Mynaphone bridge, content script: reports the playing video to the extension's service worker.
(function () {
  const isMusicSite = location.hostname === "music.youtube.com";
  let lastSig = "";

  function meta(sel, attr) {
    const el = document.querySelector(sel);
    return el ? (el.getAttribute(attr || "content") || "") : "";
  }

  function videoId() {
    const u = new URL(location.href);
    return u.searchParams.get("v") || meta('meta[itemprop="identifier"]') || "";
  }

  function nowPlayingMusicSite() {
    // music.youtube.com player bar
    const title = document.querySelector("ytmusic-player-bar .title");
    const byline = document.querySelector("ytmusic-player-bar .byline");
    const parts = byline ? Array.from(byline.querySelectorAll("a, span")).map(e => e.textContent.trim()).filter(Boolean) : [];
    // byline reads "Artist • Album • Year" with separators as text nodes
    const text = byline ? byline.textContent.replace(/\s+/g, " ").trim() : "";
    const seg = text.split("•").map(s => s.trim()).filter(Boolean);
    // songs read "Artist • Album • Year"; videos read "Artist • 245M views • 1.2M likes"
    const isCount = s => /\b(views?|likes?|subscribers?)\b/i.test(s) || /^\d{4}$/.test(s);
    const album = seg.length >= 2 && !isCount(seg[1]) ? seg[1] : "";
    return {
      title: title ? title.textContent.trim() : "",
      artist: seg[0] || "",
      album: album,
      year: (seg.find(s => /^\d{4}$/.test(s)) || ""),
      isVideo: seg.slice(1).some(s => /\b(views?|likes?)\b/i.test(s)),
      parts: parts,
    };
  }

  function description() {
    // The full description, where labels list song, film, singers, music director and lyricist.
    // YouTube keeps the whole text in the DOM and only clips it visually.
    const cands = [
      "#description-inline-expander #expanded",
      "#description-inline-expander #plain-snippet-text",
      "#description-inline-expander #snippet-text",
      "#description-inline-expander #formatted-snippet-text",
      "ytmusic-description-shelf-renderer .description",
    ].map(sel => { const el = document.querySelector(sel); return el ? el.textContent : ""; });
    const m = document.querySelector('meta[itemprop="description"]');
    if (m) cands.push(m.getAttribute("content") || "");
    return cands.reduce((a, b) => (b && b.length > a.length ? b : a), "").trim().slice(0, 4000);
  }

  function snapshot(evt) {
    const v = document.querySelector("video");
    const id = videoId();
    const s = {
      type: "youtube",
      event: evt || "tick",
      ts: Date.now(),
      url: location.href,
      host: location.hostname,
      videoId: id,
      title: meta('meta[itemprop="name"]') || document.title.replace(/ - YouTube( Music)?$/, ""),
      channel: meta('link[itemprop="name"]') || meta('span[itemprop="author"] link[itemprop="name"]') || "",
      genre: meta('meta[itemprop="genre"]'),
      isMusic: isMusicSite || meta('meta[itemprop="genre"]').toLowerCase() === "music",
      duration: v && isFinite(v.duration) ? v.duration : 0,
      position: v ? v.currentTime : 0,
      paused: v ? v.paused : true,
      seeking: v ? v.seeking : false,
      ended: v ? v.ended : false,
      playbackRate: v ? v.playbackRate : 1,
      volume: v ? v.volume : null,
      muted: v ? v.muted : false,
      music: isMusicSite ? nowPlayingMusicSite() : null,
      description: description(),
    };
    return s;
  }

  function send(evt, force) {
    const s = snapshot(evt);
    const sig = [s.videoId, s.paused, s.ended, Math.floor(s.position)].join("|");
    if (!force && sig === lastSig) return;
    lastSig = sig;
    // a report sent while the service worker is waking up rejects; that is not an error worth logging
    try { const p = chrome.runtime.sendMessage(s); if (p && p.catch) p.catch(() => {}); } catch (e) {}
  }

  function hook(v) {
    if (!v || v.__mynaphone) return;
    v.__mynaphone = true;
    ["play", "playing", "pause", "seeking", "seeked", "ended", "loadedmetadata", "ratechange"].forEach(ev =>
      v.addEventListener(ev, () => send(ev, true)));
  }

  setInterval(() => { hook(document.querySelector("video")); send("tick", false); }, 1000);
  hook(document.querySelector("video"));
  send("load", true);
})();
