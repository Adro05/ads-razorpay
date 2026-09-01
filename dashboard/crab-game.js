/* ============================================================
   Crab Header Game — engine
   Zero dependencies. Paces a crab back and forth across a
   container, auto-jumping over generated obstacles.

   Usage:
     <div class="crab-strip" data-crab-game></div>
     <script src="crab-game.js" defer></script>
   Any element with [data-crab-game] is initialized automatically
   on DOMContentLoaded. You can also call CrabHeaderGame.init(el)
   yourself for elements added later.

   Obstacle type mix (frequency/weight) is the one knob that isn't
   a CSS variable — tune OBSTACLE_TYPES below.
   ============================================================ */

(function () {
  'use strict';

  var OBSTACLE_TYPES = [
    { type: 'seaweed', weight: 2, width: 18, height: 30 },
    { type: 'rock', weight: 2, width: 26, height: 16 },
    { type: 'sandcastle', weight: 1, width: 28, height: 32 }
  ];

  function pickObstacleType() {
    var total = OBSTACLE_TYPES.reduce(function (sum, t) { return sum + t.weight; }, 0);
    var r = Math.random() * total;
    for (var i = 0; i < OBSTACLE_TYPES.length; i++) {
      r -= OBSTACLE_TYPES[i].weight;
      if (r <= 0) return OBSTACLE_TYPES[i];
    }
    return OBSTACLE_TYPES[0];
  }

  function readNumVar(el, name, fallback) {
    var raw = getComputedStyle(el).getPropertyValue(name).trim();
    var n = parseFloat(raw);
    return isNaN(n) ? fallback : n;
  }

  function readTimeVar(el, name, fallbackMs) {
    var raw = getComputedStyle(el).getPropertyValue(name).trim();
    if (!raw) return fallbackMs;
    if (raw.endsWith('ms')) return parseFloat(raw);
    if (raw.endsWith('s')) return parseFloat(raw) * 1000;
    var n = parseFloat(raw);
    return isNaN(n) ? fallbackMs : n;
  }

  var CRAB_SVG =
    '<svg class="crab-svg" viewBox="0 0 64 44" aria-hidden="true">' +
      '<g class="crab-svg__leg" style="transform:rotate(-6deg)"><line x1="18" y1="30" x2="6" y2="40" stroke="var(--crab-body-shade,#b8301c)" stroke-width="3" stroke-linecap="round"/></g>' +
      '<g class="crab-svg__leg" style="transform:rotate(4deg)"><line x1="24" y1="33" x2="14" y2="43" stroke="var(--crab-body-shade,#b8301c)" stroke-width="3" stroke-linecap="round"/></g>' +
      '<g class="crab-svg__leg" style="transform:rotate(-4deg)"><line x1="40" y1="33" x2="50" y2="43" stroke="var(--crab-body-shade,#b8301c)" stroke-width="3" stroke-linecap="round"/></g>' +
      '<g class="crab-svg__leg" style="transform:rotate(6deg)"><line x1="46" y1="30" x2="58" y2="40" stroke="var(--crab-body-shade,#b8301c)" stroke-width="3" stroke-linecap="round"/></g>' +
      '<ellipse cx="32" cy="26" rx="19" ry="13" fill="var(--crab-body-color,#e6432a)"/>' +
      '<ellipse cx="32" cy="22" rx="19" ry="9" fill="#fff" opacity="0.12"/>' +
      '<g class="crab-svg__claw crab-svg__claw--left">' +
        '<path d="M14 22 C4 18, 2 8, 10 5 C14 10, 14 16, 18 20 Z" fill="var(--crab-claw-color,#ff5c3d)"/>' +
        '<ellipse class="crab-svg__clam crab-svg__clam--left" cx="7" cy="10" rx="4" ry="3" fill="#f4e3c1" stroke="#c9a86a"/>' +
      '</g>' +
      '<g class="crab-svg__claw crab-svg__claw--right">' +
        '<path d="M50 22 C60 18, 62 8, 54 5 C50 10, 50 16, 46 20 Z" fill="var(--crab-claw-color,#ff5c3d)"/>' +
        '<ellipse class="crab-svg__clam crab-svg__clam--right" cx="57" cy="10" rx="4" ry="3" fill="#f4e3c1" stroke="#c9a86a"/>' +
      '</g>' +
      '<line x1="26" y1="15" x2="24" y2="6" stroke="var(--crab-body-shade,#b8301c)" stroke-width="2"/>' +
      '<line x1="38" y1="15" x2="40" y2="6" stroke="var(--crab-body-shade,#b8301c)" stroke-width="2"/>' +
      '<circle cx="24" cy="5" r="2.6" fill="#1a1a1a"/>' +
      '<circle cx="40" cy="5" r="2.6" fill="#1a1a1a"/>' +
    '</svg>';

  var OBSTACLE_SVG = {
    seaweed:
      '<svg viewBox="0 0 18 30" width="18" height="30" aria-hidden="true">' +
        '<g class="crab-obstacle__seaweed">' +
          '<path d="M9 30 C2 24, 14 20, 6 14 C15 9, 3 5, 9 0" fill="none" stroke="#2f9e5a" stroke-width="4" stroke-linecap="round"/>' +
        '</g>' +
      '</svg>',
    rock:
      '<svg viewBox="0 0 26 16" width="26" height="16" aria-hidden="true">' +
        '<path d="M2 16 C0 8, 6 3, 13 3 C20 3, 26 8, 24 16 Z" fill="#8a8f98"/>' +
        '<path d="M6 16 C6 11, 10 8, 13 8" fill="none" stroke="#6f747c" stroke-width="1.5" opacity=".6"/>' +
      '</svg>',
    sandcastle:
      '<svg viewBox="0 0 28 32" width="28" height="32" aria-hidden="true">' +
        '<rect x="4" y="16" width="20" height="16" fill="#e3c186"/>' +
        '<polygon points="4,16 9,8 14,16" fill="#dab26e"/>' +
        '<polygon points="14,16 19,8 24,16" fill="#dab26e"/>' +
        '<rect x="12" y="4" width="4" height="8" fill="#e3c186"/>' +
        '<g class="crab-obstacle__flag"><polygon points="16,4 24,7 16,10" fill="#4c8dff"/></g>' +
      '</svg>'
  };

  function CrabGame(root) {
    this.root = root;
    this.direction = 1; // 1 = right, -1 = left
    this.crabX = 0;
    this.lastTime = null;
    this.isJumping = false;
    this.obstacles = [];
    this.paused = false;
    this.rafId = null;

    this.speed = readNumVar(root, '--crab-speed', 55);
    this.crabSize = readNumVar(root, '--crab-size', 40);
    this.jumpDuration = readTimeVar(root, '--crab-jump-duration', 460);
    this.minGap = readNumVar(root, '--crab-obstacle-min-gap', 220);
    this.maxGap = readNumVar(root, '--crab-obstacle-max-gap', 420);
    this.margin = readNumVar(root, '--crab-turn-margin', 20);
    this.crabWidth = this.crabSize;
    this.triggerLead = this.crabWidth * 0.9 + this.speed * (this.jumpDuration / 1000) * 0.4;

    this._build();
    this._bindVisibility();

    var prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReduced) {
      this._layoutObstacles();
      return; // static, no rAF loop
    }

    this._onResize = this._debounce(this._handleResize.bind(this), 200);
    window.addEventListener('resize', this._onResize);

    this.rafId = requestAnimationFrame(this._tick.bind(this));
  }

  CrabGame.prototype._build = function () {
    this.root.classList.add('crab-strip');
    this.root.innerHTML =
      '<div class="crab-strip__water"></div>' +
      '<div class="crab-strip__ground"></div>' +
      '<div class="crab-strip__actor"><div class="crab-jump-wrap">' + CRAB_SVG + '</div></div>';
    this.actorEl = this.root.querySelector('.crab-strip__actor');
    this.jumpWrapEl = this.root.querySelector('.crab-jump-wrap');
    this.width = this.root.clientWidth;
    this._generateObstacles();
  };

  CrabGame.prototype._generateObstacles = function () {
    var frag = document.createDocumentFragment();
    this.obstacles = [];
    var x = this.margin + 60;
    while (x < this.width - this.margin) {
      var def = pickObstacleType();
      var el = document.createElement('div');
      el.className = 'crab-strip__obstacle';
      el.innerHTML = OBSTACLE_SVG[def.type];
      frag.appendChild(el);
      this.obstacles.push({ x: x, width: def.width, el: el, cleared: true });
      x += def.width + this.minGap + Math.random() * (this.maxGap - this.minGap);
    }
    // remove any old obstacle nodes, then add the fresh set
    this.root.querySelectorAll('.crab-strip__obstacle').forEach(function (n) { n.remove(); });
    this.root.appendChild(frag);
    this._layoutObstacles();
  };

  CrabGame.prototype._layoutObstacles = function () {
    this.obstacles.forEach(function (o) {
      o.el.style.left = o.x + 'px';
    });
  };

  CrabGame.prototype._handleResize = function () {
    this.width = this.root.clientWidth;
    this._generateObstacles();
    this.crabX = Math.min(this.crabX, this.width - this.margin - this.crabWidth);
  };

  CrabGame.prototype._bindVisibility = function () {
    var self = this;
    document.addEventListener('visibilitychange', function () {
      self.paused = document.hidden;
      self.root.dataset.paused = String(self.paused);
    });
    if ('IntersectionObserver' in window) {
      this._io = new IntersectionObserver(function (entries) {
        var visible = entries[0] && entries[0].isIntersecting;
        self.paused = !visible || document.hidden;
        self.root.dataset.paused = String(self.paused);
      }, { threshold: 0.01 });
      this._io.observe(this.root);
    }
  };

  CrabGame.prototype._jump = function () {
    if (this.isJumping) return;
    this.isJumping = true;
    var self = this;
    this.jumpWrapEl.classList.add('is-jumping');
    var onEnd = function () {
      self.jumpWrapEl.classList.remove('is-jumping');
      self.isJumping = false;
      self.jumpWrapEl.removeEventListener('animationend', onEnd);
    };
    this.jumpWrapEl.addEventListener('animationend', onEnd);
  };

  CrabGame.prototype._checkObstacles = function () {
    var crabFront = this.direction === 1 ? this.crabX + this.crabWidth : this.crabX;
    for (var i = 0; i < this.obstacles.length; i++) {
      var o = this.obstacles[i];
      var oNear = this.direction === 1 ? o.x : o.x + o.width;
      var dist = this.direction === 1 ? (oNear - crabFront) : (crabFront - oNear);

      if (dist < -o.width - this.crabWidth) {
        // fully passed -> re-arm for the next pass in the opposite direction
        o.cleared = true;
        continue;
      }
      if (!o.cleared) continue;
      if (dist <= this.triggerLead && dist > -o.width) {
        this._jump();
        o.cleared = false;
      }
    }
  };

  CrabGame.prototype._tick = function (time) {
    if (this.lastTime === null) this.lastTime = time;
    var dt = Math.min((time - this.lastTime) / 1000, 0.1);
    this.lastTime = time;

    if (!this.paused) {
      this.crabX += this.direction * this.speed * dt;

      var maxX = this.width - this.margin - this.crabWidth;
      var minX = this.margin;
      if (this.crabX >= maxX) { this.crabX = maxX; this.direction = -1; }
      if (this.crabX <= minX) { this.crabX = minX; this.direction = 1; }

      this.actorEl.style.transform =
        'translate3d(' + this.crabX + 'px,0,0) scaleX(' + this.direction + ')';

      this._checkObstacles();
    }

    this.rafId = requestAnimationFrame(this._tick.bind(this));
  };

  CrabGame.prototype._debounce = function (fn, wait) {
    var t;
    return function () {
      clearTimeout(t);
      var args = arguments;
      t = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  };

  CrabGame.prototype.destroy = function () {
    if (this.rafId) cancelAnimationFrame(this.rafId);
    if (this._onResize) window.removeEventListener('resize', this._onResize);
    if (this._io) this._io.disconnect();
  };

  function init(el, opts) {
    if (!el || el._crabGameInstance) return el && el._crabGameInstance;
    var instance = new CrabGame(el, opts || {});
    el._crabGameInstance = instance;
    return instance;
  }

  window.CrabHeaderGame = { init: init };

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-crab-game]').forEach(function (el) { init(el); });
  });
})();
