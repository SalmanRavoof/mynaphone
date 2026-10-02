// Copyright (C) 2026 Salman Ravoof
// SPDX-License-Identifier: GPL-3.0-or-later
// Mynaphone bridge, service worker: holds one WebSocket to the recorder and forwards page reports.
const WS_URL = "ws://127.0.0.1:8765/youtube";
let ws = null;
let queue = [];
let nextTry = 0;          // when a new connection may be attempted (ms since epoch)
let backoff = 5000;       // grows to a minute while the recorder is off, so the browser is not
                          // flooded with failed-connection errors in chrome://extensions

function connect(force) {
  if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
  const now = Date.now();
  if (!force && now < nextTry) return;
  nextTry = now + backoff;
  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    ws = null;
    return;
  }
  ws.onopen = () => { backoff = 5000; for (const m of queue) ws.send(m); queue = []; };
  ws.onclose = () => { ws = null; backoff = Math.min(backoff * 2, 60000); };
  ws.onerror = () => { try { ws.close(); } catch (e) {} ws = null; };
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || msg.type !== "youtube") return;
  msg.tabId = sender.tab ? sender.tab.id : null;
  msg.active = sender.tab ? !!sender.tab.active : null;
  const text = JSON.stringify(msg);
  connect(false);
  if (ws && ws.readyState === 1) ws.send(text);
  else { queue.push(text); if (queue.length > 20) queue.shift(); }
});

// retry while the recorder is off, backing off up to a minute between attempts
setInterval(() => connect(false), 5000);
connect(true);
