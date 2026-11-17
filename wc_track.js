/* ============================================================
 * wc_track.js  v1.2  微尘 · 行为埋点引擎
 * 纯前端、无依赖、离线可用；部署后改一行 endpoint 即可上云。
 *
 * 设计原则：
 *   1. 只记录"行为"，不记录"内容"（文本输入只记字数，不记原文）
 *   2. 本地优先（localStorage），网络失败不丢数据、不报错
 *   3. 时间一律用 performance.now() 算相对毫秒，不受网速影响
 *   4. 只标记质量，不自动删除数据（剔除规则放到分析阶段）
 * ============================================================ */
(function (global) {
  "use strict";

  /* ---------- 配置：部署时改这里 ---------- */
  var WC_CONFIG = {
    endpoint: "",                 // 例："https://api.yourdomain.com/api/events"；留空=纯本地
    study: "weichen_pilot",       // 研究代号，写进每条事件便于区分批次
    maxLocal: 2000,               // 本地最多保留多少条（超出丢最旧）
    sendBeacon: true,             // 有 endpoint 时，离开页面用 sendBeacon 兜底上报
    fastMs: 300,                  // < 300ms 判"瞎点"
    slowMs: 30000,                // > 30s  判"走神"
    flushEvery: 6,                // 攒够 6 条就自动上报一次（不依赖关页面）
    flushMs: 20000                // 每 20 秒兜底补传一次
  };

  var K = {
    sid: "wc.sid",
    pid: "wc.pid",
    arm: "wc.arm",
    ev: "wc.events",
    seq: "wc.seq",
    flushed: "wc.flushed"
  };

  var PAGE = "unknown";
  var bootT = now();
  var hiddenCount = 0;
  var hiddenMs = 0;
  var hiddenSince = null;
  var itemMap = {};        // key -> { t0, answers, hiddenAtShow, hiddenMsAtShow }
  var ready = false;

  /* ---------- 工具 ---------- */
  function now() {
    return (global.performance && performance.now) ? performance.now() : Date.now();
  }
  function uid() {
    return "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }
  function ls(k, v) {
    try {
      if (v === undefined) return localStorage.getItem(k);
      localStorage.setItem(k, v);
      return v;
    } catch (e) { return null; }   // 隐私模式静默降级
  }
  function lsDel(k) { try { localStorage.removeItem(k); } catch (e) {} }

  function readJSON(k, dft) {
    try {
      var raw = ls(k);
      if (!raw) return dft;
      var v = JSON.parse(raw);
      return v === null || v === undefined ? dft : v;
    } catch (e) { return dft; }
  }

  /* 页名兜底：即使 init 还没跑，也不会记成 unknown */
  function pgName() {
    if (PAGE && PAGE !== "unknown") return PAGE;
    try {
      var f = (location.pathname || "").split("/").pop().toLowerCase();
      return f ? f.replace(/\.html?$/, "") : "unknown";
    } catch (e) { return "unknown"; }
  }

  function query(name) {
    try {
      var m = new RegExp("[?&]" + name + "=([^&#]*)").exec(location.search);
      return m ? decodeURIComponent(m[1]) : "";
    } catch (e) { return ""; }
  }

  /* ---------- 身份：被试编号 / 组别 / 会话 ---------- */
  function ensureId() {
    var qp = query("pid");
    if (qp) ls(K.pid, qp);
    var qa = query("arm");
    if (qa) ls(K.arm, String(qa).toUpperCase());
    if (!ls(K.sid)) ls(K.sid, uid());
    return {
      pid: ls(K.pid) || "",
      arm: ls(K.arm) || "",
      sid: ls(K.sid) || ""
    };
  }

  /* ---------- 事件写入 ---------- */
  function push(evt, payload, q) {
    var id = ensureId();
    var seq = (parseInt(ls(K.seq) || "0", 10) || 0) + 1;
    ls(K.seq, String(seq));

    var e = {
      e: evt,
      seq: seq,
      t: Date.now(),
      rt: Math.round(now() - bootT),
      pg: pgName(),
      sid: id.sid,
      pid: id.pid,
      arm: id.arm,
      study: WC_CONFIG.study
    };
    if (q) e.q = q;
    e.hc = hiddenCount;
    e.hm = Math.round(hiddenMs);
    if (payload) e.x = payload;

    var arr = readJSON(K.ev, []);
    arr.push(e);
    if (arr.length > WC_CONFIG.maxLocal) arr = arr.slice(-WC_CONFIG.maxLocal);
    try { ls(K.ev, JSON.stringify(arr)); } catch (xf) {
      // 配额满了：丢掉一半重试
      try { ls(K.ev, JSON.stringify(arr.slice(-Math.floor(WC_CONFIG.maxLocal / 2)))); } catch (e2) {}
    }

    /* 攒够就上报，不用等关页面；失败也不影响本地留存 */
    if (WC_CONFIG.endpoint) {
      var flushed = parseInt(ls(K.flushed) || "0", 10) || 0;
      if (arr.length - flushed >= (WC_CONFIG.flushEvery || 6)) WC.flush(false);
    }
    return e;
  }

  /* ---------- 质量标记 ---------- */
  function qualityOf(rtMs, hiddenDuring) {
    if (hiddenDuring) return "hidden_overlap";
    if (rtMs < WC_CONFIG.fastMs) return "too_fast";
    if (rtMs > WC_CONFIG.slowMs) return "too_slow";
    return "ok";
  }

  /* ---------- 对外 API ---------- */
  var WC = {

    config: WC_CONFIG,
    version: "1.3",

    /* 初始化：每个页面开头调一次 */
    init: function (opts) {
      opts = opts || {};
      PAGE = opts.page || PAGE;
      WC_CONFIG = WC.config = Object.assign ? Object.assign(WC_CONFIG, opts.config || {}) : WC_CONFIG;
      var id = ensureId();
      if (!id.sid) ls(K.sid, uid());
      ready = true;
      WC.track("page_view", { href: (location.pathname || "").split("/").pop(), ref: document.referrer ? 1 : 0 });
      WC._watchHidden();
      if (WC_CONFIG.endpoint && !WC._timer) {
        WC._timer = setInterval(function () { WC.flush(false); }, Math.max(5000, WC_CONFIG.flushMs || 20000));
        setTimeout(function () { WC.retryPending(); }, 600);   // 承接上一页没送出去的数据
      }
      return id;
    },

    /* 随机分组：正式实验 A/B 各 50%；返回最终组别 */
    assignArm: function (force) {
      var cur = ls(K.arm) || "";
      if (force || !cur) {
        ls(K.arm, force ? String(force).toUpperCase() : (Math.random() < 0.5 ? "A" : "B"));
      }
      return ls(K.arm);
    },
    getArm: function () { return (ls(K.arm) || "").toUpperCase(); },

    /* 通用事件 */
    track: function (evt, payload) {
      return push(evt, payload);
    },

    /* 题目出现：开始计时 */
    show: function (key, payload) {
      /* 同一题 3 秒内重复渲染不再记一次（页面会连调两次 render），也不重置计时 */
      var prev = itemMap[key];
      if (prev && (now() - prev.t0) < 3000) return prev;
      itemMap[key] = {
        t0: now(),
        answers: 1,
        hiddenAtShow: hiddenCount,
        hiddenMsAtShow: hiddenMs
      };
      push("item_show", Object.assign ? Object.assign({ key: key }, payload || {}) : (payload || { key: key }));
    },

    /* 题目作答：算 RT、判质量、计修改次数 */
    answer: function (key, value, payload) {
      var it = itemMap[key] || (itemMap[key] = { t0: now(), answers: 0, hiddenAtShow: hiddenCount, hiddenMsAtShow: hiddenMs });
      var rtMs = Math.round(now() - it.t0);
      var hidDelta = hiddenMs - (it.hiddenMsAtShow || 0);
      var rev = it.answers || 1;

      var extra = {};
      if (payload) for (var k in payload) if (payload.hasOwnProperty(k)) extra[k] = payload[k];
      extra.key = key;
      extra.v = value;
      extra.rtMs = rtMs;            // 单题反应时（毫秒）——DDM / 犹豫指标就用它
      extra.rev = rev;              // 1 = 第一次作答，2+ = 回头改了
      extra.hm = Math.round(hidDelta);

      var q = qualityOf(rtMs, hidDelta > 500);
      push("item_answer", extra, q);

      it.answers = rev + 1;
      it.t0 = now();                // 重答重新计时
      it.hiddenMsAtShow = hiddenMs;
      return { rtMs: rtMs, rev: rev, q: q };
    },

    /* 离开某题（切 tab / 返回上一题） */
    leave: function (key, reason) {
      push("item_leave", { key: key, reason: reason || "next" });
    },

    /* 对话/文本输入：只记字数，绝不存原文 */
    textLen: function (channel, text) {
      var t = String(text || "");
      // 中文按字、英文按词粗估，只保留长度
      var zh = (t.match(/[\u4e00-\u9fa5]/g) || []).length;
      var en = (t.replace(/[\u4e00-\u9fa5]/g, " ").trim().match(/[A-Za-z]+/g) || []).length;
      return { ch: zh, wd: en, total: zh + en, empty: t.trim() ? 0 : 1, channel: channel };
    },

    /* 自查：把这个对象贴给老师/写进论文，一眼看出采没采到 */
    health: function () {
      var arr = readJSON(K.ev, []);
      var id = ensureId();
      var types = {};
      arr.forEach(function (e) { types[e.e] = (types[e.e] || 0) + 1; });
      var bad = arr.filter(function (e) { return e.q && e.q !== "ok"; }).length;
      var bytes = 0;
      try { bytes = (ls(K.ev) || "").length; } catch (e) {}
      return {
        version: WC.version,
        page: PAGE,
        pid: id.pid || "(未绑定)",
        arm: id.arm || "(未分组)",
        events: arr.length,
        flagged: bad,
        localBytes: bytes,
        endpoint: WC_CONFIG.endpoint || "(纯本地)",
        firstEventTime: arr.length ? new Date(arr[0].t).toLocaleString() : "-",
        lastEventTime: arr.length ? new Date(arr[arr.length - 1].t).toLocaleString() : "-",
        types: types
      };
    },

    /* 导出：JSONL 一行一条，方便 pandas 直接读 */
    toJSONL: function () {
      return readJSON(K.ev, []).map(function (e) { return JSON.stringify(e); }).join("\n");
    },

    download: function (tag) {
      var id = ensureId();
      var name = "wc_" + (id.pid || "anon") + "_" + (id.arm || "NA") + "_" +
        (tag || PAGE) + "_" + new Date().toISOString().slice(0, 10).replace(/-/g, "") + ".jsonl";
      var blob = new Blob([WC.toJSONL()], { type: "application/x-ndjson;charset=utf-8" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.style.display = "none";
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 300);
      return name;
    },

    /* 清空：开新被试前必须调用（否则上一人的数据会混进来） */
    clearAll: function (keepArm) {
      lsDel(K.ev); lsDel(K.seq); lsDel(K.flushed);
      if (!keepArm) { lsDel(K.pid); lsDel(K.arm); }
      ls(K.sid, uid());
      return true;
    },

    /* 上报：endpoint 为空时什么都不做
       只有服务器真的回了 2xx 才记"已上报"；失败就留在本地，下次自动重试。
       （早期用 sendBeacon 乐观标记，结果页面跳转时会丢数据，已改掉） */
    flush: function (useBeacon) {
      if (!WC_CONFIG.endpoint) return 0;
      var arr = readJSON(K.ev, []);
      var sent = parseInt(ls(K.flushed) || "0", 10) || 0;
      var todo = arr.slice(sent);
      if (!todo.length) return 0;
      var body = JSON.stringify(todo);
      var total = arr.length;
      var mark = function () { ls(K.flushed, String(total)); };
      try {
        fetch(WC_CONFIG.endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: body,
          keepalive: true
        }).then(function (r) { if (r && r.ok) mark(); }).catch(function () {});
        return todo.length;
      } catch (e) { return 0; }
    },

    /* 补传：进入页面时先把上次没送出去的补上 */
    retryPending: function () {
      if (!WC_CONFIG.endpoint) return 0;
      return WC.flush(false);
    },

    /* 切屏监控（内部） */
    _watchHidden: function () {
      document.addEventListener("visibilitychange", function () {
        if (document.hidden) {
          hiddenCount++;
          hiddenSince = now();
          WC.flush(true);
        } else {
          if (hiddenSince !== null) {
            hiddenMs += (now() - hiddenSince);
            hiddenSince = null;
          }
          WC.flush(false);
        }
      });
      global.addEventListener("pagehide", function () { WC.flush(true); });
    },

    /* 调试用：控制台 WC.dump() */
    dump: function () { return readJSON(K.ev, []); },
    setPid: function (pid) { ls(K.pid, String(pid || "")); return ls(K.pid); },
    setArm: function (arm) { ls(K.arm, String(arm || "").toUpperCase()); return ls(K.arm); }
  };

  global.WC = WC;
})(window);
