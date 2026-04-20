/**
 * Mascot — video-driven interactive fox widget.
 *
 * Architecture: two dedicated <video> layers.
 *   - idleLayer: permanently loaded with idle loop, always playing
 *   - reactionLayer: swaps src per reaction; plays once
 *
 * On reaction: fade out idle, fade in reaction, wait for end, fade back to idle.
 * Idle's src is never touched after init — no reload flashes.
 */

const REACTIONS = [
  "wave",
  "laugh",
  "poke_reaction",
  "tickle_belly",
  "tickle_feet",
  "angry",
  "happy",
  "sad",
  "sleepy",
  "pointing_right",
];

const HIT_ZONES = [
  { name: "head", x: [0.30, 0.70], y: [0.00, 0.35], reactions: ["poke_reaction", "wave", "happy", "angry"] },
  { name: "body", x: [0.20, 0.80], y: [0.35, 0.70], reactions: ["tickle_belly", "laugh"] },
  { name: "legs", x: [0.20, 0.80], y: [0.70, 1.00], reactions: ["tickle_feet"] },
];

const FADE_MS = 150;

class Mascot {
  constructor(root, options = {}) {
    this.root = root;
    this.videosUrl = options.videosUrl || "./assets/videos/";
    this.idleClip = `${this.videosUrl}idle_breathing_loop.mp4`;
    this.isBusy = false;
    this._build();
    this._startIdle();
  }

  _build() {
    this.root.classList.add("mascot-container");

    const nameTag = document.createElement("div");
    nameTag.className = "mascot-nametag";
    nameTag.innerHTML = `
      <span class="mascot-nametag-header">Olá, meu nome é</span>
      <span class="mascot-nametag-name">TED</span>
    `;
    this.root.appendChild(nameTag);

    const stage = document.createElement("div");
    stage.className = "mascot-stage";
    this.stage = stage;
    this.root.appendChild(stage);

    this.idleLayer = this._createVideo("idle");
    this.reactionLayer = this._createVideo("reaction");
    this.idleLayer.classList.add("active");
    stage.appendChild(this.idleLayer);
    stage.appendChild(this.reactionLayer);

    const hint = document.createElement("div");
    hint.className = "mascot-hint";
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

  _createVideo(kind) {
    const v = document.createElement("video");
    v.className = `mascot-video mascot-video-${kind}`;
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

  _handleTap(event) {
    if (this.isBusy) return;

    const rect = this.stage.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;

    if (x < 0 || x > 1 || y < 0 || y > 1) {
      this.react(this._randomChoice(["wave", "happy", "pointing_right"]));
      return;
    }
    const zone = HIT_ZONES.find(z =>
      x >= z.x[0] && x <= z.x[1] && y >= z.y[0] && y <= z.y[1]
    );
    this.react(zone ? this._randomChoice(zone.reactions) : "wave");
  }

  _randomChoice(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

  /**
   * Play a reaction clip, then cross-fade back to the idle loop.
   */
  async react(name) {
    if (this.isBusy) return;
    if (!REACTIONS.includes(name)) {
      console.warn(`Unknown reaction: ${name}`);
      return;
    }
    this.isBusy = true;

    const clipUrl = `${this.videosUrl}${name}_seamless.mp4`;
    const r = this.reactionLayer;

    try {
      // Load reaction clip
      r.src = clipUrl;
      r.loop = false;
      r.currentTime = 0;
      await this._waitCanPlay(r);

      // Start playing reaction
      const endedPromise = this._waitEnded(r);
      await r.play().catch(() => {});

      // Cross-fade: show reaction layer
      r.classList.add("active");
      // Idle keeps playing underneath but fades out
      this.idleLayer.classList.remove("active");

      // Wait for reaction to finish
      await endedPromise;

      // Reset idle to start (idle_stand pose) so it aligns with reaction's end pose
      this.idleLayer.currentTime = 0;
      // Make sure idle is still playing (should be, but just in case)
      await this.idleLayer.play().catch(() => {});

      // Cross-fade back to idle
      this.idleLayer.classList.add("active");
      r.classList.remove("active");

      // Wait for fade to complete before releasing busy, so a rapid second tap
      // doesn't interrupt the cross-fade
      await new Promise(res => setTimeout(res, FADE_MS));
    } catch (e) {
      console.warn(`Reaction '${name}' failed:`, e.message);
      // Recovery: ensure idle is visible
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
      const cleanup = () => {
        video.removeEventListener("canplay", onCanPlay);
        video.removeEventListener("error", onError);
      };
      const onCanPlay = () => { if (done) return; done = true; cleanup(); resolve(); };
      const onError = () => { if (done) return; done = true; cleanup(); reject(new Error("video load error")); };
      video.addEventListener("canplay", onCanPlay);
      video.addEventListener("error", onError);
      setTimeout(() => { if (done) return; done = true; cleanup(); reject(new Error("video load timeout")); }, timeoutMs);
    });
  }

  _waitEnded(video) {
    return new Promise(resolve => {
      const handler = () => {
        video.removeEventListener("ended", handler);
        resolve();
      };
      video.addEventListener("ended", handler);
    });
  }
}

window.Mascot = Mascot;
