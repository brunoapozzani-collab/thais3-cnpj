/**
 * TED — Embeddable interactive fox mascot.
 *
 * Usage:
 *   const ted = TED.init(container, {
 *     videosUrl: 'https://…/mascot-assets/',
 *     trashTalkEndpoint: '/api/trash-talk',
 *     name: 'TED',
 *   });
 *   ted.onEvent('page_load', { pageName: 'Debora 3#' });
 *   ted.react('wave');
 *   ted.say('Fala, parceiro!', 'wave');
 */

(function () {
  "use strict";

  const REACTIONS = [
    "wave", "laugh", "poke_reaction", "tickle_belly", "tickle_feet",
    "angry", "happy", "sad", "sleepy", "pointing_right",
  ];

  const HIT_ZONES = [
    { y: [0.00, 0.35], reactions: ["poke_reaction", "wave", "happy", "angry"] },
    { y: [0.35, 0.70], reactions: ["tickle_belly", "laugh"] },
    { y: [0.70, 1.00], reactions: ["tickle_feet"] },
  ];

  const FALLBACK_LINES = [
    { animation: "wave", text: "E aí, sumido! Tava com saudade 😏" },
    { animation: "laugh", text: "Hahaha, tu é corajoso, hein!" },
    { animation: "pointing_right", text: "Bora trabalhar, preguiçoso!" },
    { animation: "happy", text: "Que bom te ver de novo! 🦊" },
    { animation: "sleepy", text: "Tô de boa aqui, relaxa..." },
    { animation: "angry", text: "Ei! Para de me cutucar! 😤" },
    { animation: "laugh", text: "Tu digita que nem meu avô 🐢" },
    { animation: "pointing_right", text: "Isso aí, vai nessa!" },
    { animation: "happy", text: "Opa, mandou bem!" },
    { animation: "sad", text: "Poxa, deu ruim..." },
    { animation: "wave", text: "Olha só quem apareceu! 👋" },
    { animation: "laugh", text: "Calma aí, tô processando a zoeira" },
    { animation: "poke_reaction", text: "Eita! Que susto, parça!" },
    { animation: "angry", text: "Quer parar? Tô trabalhando aqui!" },
    { animation: "sleepy", text: "Boceja… tá lento hoje, hein?" },
    { animation: "happy", text: "Sou o TED, prazer! Agora trabalha!" },
  ];

  const BUBBLE_DURATION_MS = 5000;
  const DEBOUNCE_MS = 2500;
  const RATE_LIMIT_MS = 3000;
  const FADE_MS = 150;

  class TedMascot {
    constructor(root, options = {}) {
      this.root = root;
      this.videosUrl = (options.videosUrl || "./assets/videos/").replace(/\/?$/, "/");
      this.trashTalkEndpoint = options.trashTalkEndpoint || null;
      this.name = options.name || "TED";
      this.idleClip = `${this.videosUrl}idle_breathing_loop.mp4`;

      this.isBusy = false;
      this._bubbleTimer = null;
      this._debounceTimers = {};
      this._lastLlmCall = 0;

      this._build();
      this._startIdle();
    }

    // ── Public API ──

    react(name) {
      if (this.isBusy || !REACTIONS.includes(name)) return;
      this._playReaction(name);
    }

    say(text, animation) {
      if (animation && REACTIONS.includes(animation)) {
        this._playReaction(animation);
      }
      this._showBubble(text);
    }

    onEvent(eventName, context = {}) {
      const key = eventName;
      if (this._debounceTimers[key]) clearTimeout(this._debounceTimers[key]);

      if (eventName === "page_load") {
        this._callTrashTalk(eventName, context);
        return;
      }

      this._debounceTimers[key] = setTimeout(() => {
        this._callTrashTalk(eventName, context);
      }, DEBOUNCE_MS);
    }

    // ── Build DOM ──

    _build() {
      this.root.classList.add("ted-root");

      const nametag = document.createElement("div");
      nametag.className = "ted-nametag";
      nametag.innerHTML = `
        <span class="ted-nametag-header">Olá, meu nome é</span>
        <span class="ted-nametag-name">${this.name}</span>
      `;
      this.root.appendChild(nametag);

      this.bubble = document.createElement("div");
      this.bubble.className = "ted-bubble";
      this.root.appendChild(this.bubble);

      const stage = document.createElement("div");
      stage.className = "ted-stage";
      this.stage = stage;
      this.root.appendChild(stage);

      this.idleLayer = this._mkVideo("idle");
      this.reactionLayer = this._mkVideo("reaction");
      this.idleLayer.classList.add("active");
      stage.appendChild(this.idleLayer);
      stage.appendChild(this.reactionLayer);

      const hint = document.createElement("div");
      hint.className = "ted-hint";
      hint.textContent = "toque para interagir";
      this.root.appendChild(hint);

      this.root.addEventListener("click", (e) => this._handleTap(e));
      this.root.addEventListener("touchstart", (e) => {
        if (e.touches.length > 0) {
          const t = e.touches[0];
          this._handleTap({ clientX: t.clientX, clientY: t.clientY });
        }
      }, { passive: true });
    }

    _mkVideo(kind) {
      const v = document.createElement("video");
      v.className = `ted-video ted-video-${kind}`;
      v.muted = true;
      v.playsInline = true;
      v.preload = "auto";
      v.setAttribute("webkit-playsinline", "true");
      return v;
    }

    _startIdle() {
      this.idleLayer.src = this.idleClip;
      this.idleLayer.loop = true;
      this.idleLayer.play().catch(() => {});
    }

    // ── Tap Handler ──

    _handleTap(event) {
      if (this.isBusy) return;
      const rect = this.stage.getBoundingClientRect();
      const y = (event.clientY - rect.top) / rect.height;

      const zone = HIT_ZONES.find(z => y >= z.y[0] && y <= z.y[1]);
      const reaction = zone
        ? zone.reactions[Math.floor(Math.random() * zone.reactions.length)]
        : "wave";

      this._callTrashTalk("poke", { bodyPart: zone ? zone.y[0] < 0.35 ? "head" : zone.y[0] < 0.7 ? "body" : "feet" : "outside" });
    }

    // ── Video Playback ──

    async _playReaction(name) {
      if (this.isBusy) return;
      this.isBusy = true;

      const clipUrl = `${this.videosUrl}${name}_seamless.mp4`;
      const r = this.reactionLayer;

      try {
        r.src = clipUrl;
        r.loop = false;
        r.currentTime = 0;
        await this._waitCanPlay(r);

        const endedPromise = this._waitEnded(r);
        await r.play().catch(() => {});

        r.classList.add("active");
        this.idleLayer.classList.remove("active");

        await endedPromise;

        this.idleLayer.currentTime = 0;
        await this.idleLayer.play().catch(() => {});
        this.idleLayer.classList.add("active");
        r.classList.remove("active");

        await new Promise(res => setTimeout(res, FADE_MS));
      } catch (e) {
        this.idleLayer.classList.add("active");
        r.classList.remove("active");
        r.pause();
      }

      this.isBusy = false;
    }

    _waitCanPlay(video, timeoutMs = 5000) {
      return new Promise((resolve, reject) => {
        if (video.readyState >= 3) return resolve();
        let done = false;
        const cleanup = () => { video.removeEventListener("canplay", ok); video.removeEventListener("error", fail); };
        const ok = () => { if (done) return; done = true; cleanup(); resolve(); };
        const fail = () => { if (done) return; done = true; cleanup(); reject(new Error("load error")); };
        video.addEventListener("canplay", ok);
        video.addEventListener("error", fail);
        setTimeout(() => { if (done) return; done = true; cleanup(); reject(new Error("timeout")); }, timeoutMs);
      });
    }

    _waitEnded(video) {
      return new Promise(resolve => {
        const h = () => { video.removeEventListener("ended", h); resolve(); };
        video.addEventListener("ended", h);
      });
    }

    // ── Speech Bubble ──

    _showBubble(text) {
      if (!text) return;
      clearTimeout(this._bubbleTimer);
      this.bubble.textContent = text;
      this.bubble.classList.add("visible");
      this._bubbleTimer = setTimeout(() => {
        this.bubble.classList.remove("visible");
      }, BUBBLE_DURATION_MS);
    }

    // ── LLM Integration ──

    async _callTrashTalk(event, context) {
      const now = Date.now();
      if (now - this._lastLlmCall < RATE_LIMIT_MS) {
        this._useFallback(event);
        return;
      }

      if (!this.trashTalkEndpoint) {
        this._useFallback(event);
        return;
      }

      this._lastLlmCall = now;

      try {
        const resp = await fetch(this.trashTalkEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ event, context }),
        });

        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const data = await resp.json();
        const anim = REACTIONS.includes(data.animation) ? data.animation : "wave";
        const text = (data.text || "").slice(0, 120);

        if (text) this._showBubble(text);
        if (anim) this._playReaction(anim);
      } catch (e) {
        console.warn("TED trash-talk failed:", e.message);
        this._useFallback(event);
      }
    }

    _useFallback(event) {
      const eventMap = {
        page_load: ["wave", "happy"],
        cnpj_typing: ["pointing_right", "laugh"],
        lookup_started: ["happy", "pointing_right"],
        lookup_result: ["happy", "laugh", "wave"],
        lookup_error: ["sad", "angry"],
        idle_tick: ["sleepy", "wave", "pointing_right"],
        poke: ["poke_reaction", "angry", "tickle_belly", "laugh"],
      };
      const pool = eventMap[event] || ["wave"];
      const anim = pool[Math.floor(Math.random() * pool.length)];
      const matching = FALLBACK_LINES.filter(l => l.animation === anim);
      const line = matching.length > 0
        ? matching[Math.floor(Math.random() * matching.length)]
        : FALLBACK_LINES[Math.floor(Math.random() * FALLBACK_LINES.length)];

      this._showBubble(line.text);
      this._playReaction(line.animation);
    }
  }

  // ── Global entry point ──

  window.TED = {
    init(container, options) {
      return new TedMascot(container, options);
    },
  };
})();
