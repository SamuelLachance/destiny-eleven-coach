/**
 * Destiny Eleven save codec — decode localStorage destinyEleven_current
 * Format: v1.<checksum36>.<btoa(xor_stream(utf8(json)))>
 * Salt recovered from game.js (_0x3ddada(0x155)).
 */
(function (global) {
  const SALT = "d11\u00b75c3n3\u00b7k3y\u00b7v1\u00b72026";

  function seedFromSalt(salt) {
    let s = 0;
    for (let i = 0; i < 0x15; i++) {
      s = (Math.imul(s, 0x83) + salt.charCodeAt(i)) | 0;
    }
    return (s >>> 0) || 1;
  }

  function xorStream(str, salt) {
    let state = seedFromSalt(salt || SALT);
    let out = "";
    for (let i = 0; i < str.length; i++) {
      state = (state + 0x6d2b79f5) | 0;
      let x = Math.imul(state ^ (state >>> 15), 1 | state);
      x = (x + Math.imul(x ^ (x >>> 7), 0x3d | x)) ^ x;
      out += String.fromCharCode(str.charCodeAt(i) ^ (((x ^ (x >>> 14)) >>> 0) & 0xff));
    }
    return out;
  }

  function checksum(text, salt) {
    salt = salt || SALT;
    const seed = seedFromSalt(salt);
    const s = text + salt;
    let h1 = (0xdeadbeef ^ seed) >>> 0;
    let h2 = (0x41c6ce57 ^ seed) >>> 0;
    for (let i = 0; i < s.length; i++) {
      const c = s.charCodeAt(i);
      h1 = Math.imul(h1 ^ c, 0x9e3779b1);
      h2 = Math.imul(h2 ^ c, 0x5f356495);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 0x85ebca6b) ^ Math.imul(h2 ^ (h2 >>> 13), 0xc2b2ae35);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 0x85ebca6b) ^ Math.imul(h1 ^ (h1 >>> 13), 0xc2b2ae35);
    const n = 0x100000000 * (0x1fffff & h2) + (h1 >>> 0);
    return n.toString(36);
  }

  function decode(raw, salt) {
    if (raw == null) return null;
    const s = String(raw);
    if (!s.startsWith("v1.")) {
      try {
        return JSON.parse(s);
      } catch (e) {
        return null;
      }
    }
    const dot = s.indexOf(".", 3);
    if (dot < 0) return null;
    const chk = s.slice(3, dot);
    const b64 = s.slice(dot + 1);
    try {
      const xorred = atob(b64);
      const text = decodeURIComponent(escape(xorStream(xorred, salt || SALT)));
      if (checksum(text, salt || SALT) !== chk) return null;
      return JSON.parse(text);
    } catch (e) {
      return null;
    }
  }

  function readPlayerFromStorage() {
    try {
      const raw = localStorage.getItem("destinyEleven_current");
      const obj = decode(raw);
      if (!obj || !obj.g) return null;
      return summarizePlayer(obj.g);
    } catch (e) {
      return null;
    }
  }

  function summarizePlayer(g) {
    if (!g || typeof g !== "object") return null;
    const st = g.stats || {};
    const t = Number(st.t != null ? st.t : g.t) || 0;
    const p = Number(st.p != null ? st.p : g.p) || 0;
    const m = Number(st.m != null ? st.m : g.m) || 0;
    const c = Number(st.c != null ? st.c : g.c) || 0;
    const ovr =
      g.ovr != null
        ? Number(g.ovr)
        : Math.round((t + p + m + c) / 4);
    const club = g.club;
    const clubName = club && typeof club === "object" ? club.name || club.id : club;
    const clubLevel = club && typeof club === "object" ? club.level : null;
    const pos = g.position && typeof g.position === "object" ? g.position.id || g.position.name : g.pos || g.position;
    return {
      age: Number(g.age) || null,
      year: Number(g.year) || null,
      ovr,
      peakOvr: Number(g.peakOvr) || ovr,
      potCap: Number(g.potCap) || null,
      t,
      p,
      m,
      c,
      rep: Number(g.rep) || 0,
      form: Number(g.form) || 50,
      moral: Number(g.moral) || 50,
      discipline: Number(g.discipline) || 50,
      coachRel: Number(g.coachRel) || 50,
      teamRel: Number(g.teamRel) || 50,
      injuryWeeks: Number(g.injuryWeeks) || 0,
      traits: Array.isArray(g.traits) ? g.traits : [],
      flags: Array.isArray(g.flags) ? g.flags : [],
      club: clubName || null,
      clubLevel: clubLevel || null,
      pos: pos || null,
      retiring: !!g.retiring,
      careerEnded: !!g.careerEnded,
      money: Number(g.money) || 0,
      matches: g.totals && g.totals.matches != null ? Number(g.totals.matches) : 0,
    };
  }

  /** Career phase from live stats — used to bias advice (trajectory). */
  function careerPhase(player) {
    if (!player) return "unknown";
    const age = player.age || 20;
    const ovr = player.ovr || 50;
    const pot = player.potCap || 80;
    const room = pot - ovr;
    if (player.injuryWeeks > 0) return "injured";
    if (age >= 34 || player.retiring) return "decline";
    if (age <= 21 || (ovr < 68 && room >= 12)) return "develop";
    if (ovr >= 78 || (player.rep || 0) >= 55) return "peak";
    return "prime";
  }

  global.D11SaveCodec = {
    SALT,
    decode,
    checksum,
    xorStream,
    readPlayerFromStorage,
    summarizePlayer,
    careerPhase,
  };
})(window);
