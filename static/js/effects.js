// Effets saisonniers : la liste vient du serveur (<html data-effects="noel trente">), calculée selon la date.
// Un seul canvas plein écran, transparent aux clics ; arrêt automatique quand l'onglet est caché.
(function () {
  "use strict";

  var root = document.documentElement;
  var list = (root.dataset.effects || "").split(" ").filter(Boolean);
  var off = false;
  try { off = localStorage.getItem("effects") === "off"; } catch (e) { /* stockage indisponible */ }

  // Bouton du pied de page : couper / remettre les effets
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-effects-toggle]");
    if (!btn) return;
    try { localStorage.setItem("effects", off ? "on" : "off"); } catch (err) { /* rien */ }
    location.reload();
  });
  var label = document.querySelector("[data-effects-toggle]");
  if (label) label.textContent = off ? label.dataset.on : label.dataset.off;

  if (!list.length || off) { root.classList.add("effects-off"); return; }
  root.classList.add("effects-on");
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return; // décor statique seulement (CSS)

  var canvas = document.createElement("canvas");
  canvas.className = "effects-canvas";
  canvas.setAttribute("aria-hidden", "true");
  document.body.appendChild(canvas);
  var ctx = canvas.getContext("2d");
  var W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();
  window.addEventListener("resize", resize);

  var rand = function (a, b) { return a + Math.random() * (b - a); };
  var particles = [];
  var has = function (code) { return list.indexOf(code) !== -1; };
  var isHome = document.body.classList.contains("page-home");
  var firstVisit = true;
  try { firstVisit = !sessionStorage.getItem("effects-burst"); sessionStorage.setItem("effects-burst", "1"); } catch (e) { /* rien */ }

  // Confettis (anniversaire, 30 ans) : une salve à la première page vue de la session
  function confetti(colors, count) {
    for (var i = 0; i < count; i++) {
      particles.push({
        kind: "confetti", x: rand(0, W), y: rand(-H * 0.4, -10), vx: rand(-0.6, 0.6), vy: rand(1.2, 3),
        r: rand(4, 8), a: rand(0, Math.PI), va: rand(-0.12, 0.12), color: colors[i % colors.length], life: 1
      });
    }
  }
  // Œufs pastel (Pâques) : quelques-uns qui tombent lentement
  function eggs(count) {
    var colors = ["#f7c6d9", "#bfe3f5", "#f9e79f", "#c8ead1", "#dccbf2"];
    for (var i = 0; i < count; i++) {
      particles.push({ kind: "egg", x: rand(0, W), y: rand(-H, -20), vx: rand(-0.2, 0.2), vy: rand(0.5, 1.1),
        r: rand(7, 11), a: rand(-0.4, 0.4), va: rand(-0.01, 0.01), color: colors[i % colors.length], life: 1 });
    }
  }
  // Flocons (Noël) : en continu, discrets
  function snow(count) {
    for (var i = 0; i < count; i++) {
      particles.push({ kind: "snow", x: rand(0, W), y: rand(-H, H), vx: rand(-0.3, 0.3), vy: rand(0.3, 1),
        r: rand(1.2, 3.2), a: rand(0, 6.28), va: rand(0.005, 0.02), life: 1, loop: true });
    }
  }
  // Chauves-souris (Halloween) : une de temps en temps traverse l'écran
  function bat() {
    var left = Math.random() < 0.5;
    particles.push({ kind: "bat", x: left ? -40 : W + 40, y: rand(H * 0.12, H * 0.5), vx: left ? rand(1.8, 3) : -rand(1.8, 3),
      vy: rand(-0.3, 0.3), r: rand(10, 16), a: 0, va: 0.25, life: 1 });
  }
  // Feux d'artifice (nouvel an)
  function firework() {
    var x = rand(W * 0.15, W * 0.85), y = rand(H * 0.12, H * 0.4);
    var colors = ["#f6c431", "#3894c0", "#ffffff", "#e2574c", "#9be3c2"];
    var color = colors[Math.floor(rand(0, colors.length))];
    for (var i = 0; i < 46; i++) {
      var angle = (Math.PI * 2 * i) / 46, speed = rand(1.2, 3.2);
      particles.push({ kind: "spark", x: x, y: y, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed,
        r: rand(1.2, 2.2), color: color, life: 1, decay: rand(0.012, 0.02) });
    }
  }

  var brand = ["#1460a6", "#3894c0", "#f6c431", "#0f1d2e", "#e2574c"];
  if ((has("anniversaire") || has("trente")) && firstVisit) confetti(brand, isHome ? 140 : 70);
  if (has("paques") && firstVisit) eggs(14);
  if (has("noel")) snow(Math.round(Math.min(90, W / 14)));
  if (has("nouvel-an") && firstVisit) { firework(); setTimeout(firework, 700); setTimeout(firework, 1500); }
  var batTimer = has("halloween") ? setInterval(function () { if (!document.hidden) bat(); }, 7000) : null;
  if (has("halloween")) setTimeout(bat, 1200);
  var fwTimer = has("nouvel-an") ? setInterval(function () { if (!document.hidden && Math.random() < 0.35) firework(); }, 6000) : null;

  function drawBat(p) {
    var flap = Math.sin(p.a) * 0.6;
    ctx.save(); ctx.translate(p.x, p.y); ctx.scale(p.vx < 0 ? -1 : 1, 1);
    ctx.fillStyle = "rgba(20, 16, 28, .85)";
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.quadraticCurveTo(-p.r * 0.6, -p.r * (0.5 + flap), -p.r * 1.6, -p.r * flap);
    ctx.quadraticCurveTo(-p.r, p.r * 0.1, -p.r * 0.5, p.r * 0.25);
    ctx.quadraticCurveTo(-p.r * 0.2, 0, 0, p.r * 0.35);
    ctx.quadraticCurveTo(p.r * 0.2, 0, p.r * 0.5, p.r * 0.25);
    ctx.quadraticCurveTo(p.r, p.r * 0.1, p.r * 1.6, -p.r * flap);
    ctx.quadraticCurveTo(p.r * 0.6, -p.r * (0.5 + flap), 0, 0);
    ctx.fill(); ctx.restore();
  }

  var running = true;
  function frame() {
    if (!running) return;
    ctx.clearRect(0, 0, W, H);
    for (var i = particles.length - 1; i >= 0; i--) {
      var p = particles[i];
      p.x += p.vx; p.y += p.vy; p.a += p.va || 0;
      if (p.kind === "snow") {
        p.x += Math.sin(p.a) * 0.3;
        if (p.y > H + 5) { p.y = -5; p.x = rand(0, W); }
        ctx.fillStyle = "rgba(255, 255, 255, .85)";
        ctx.strokeStyle = "rgba(56, 148, 192, .35)";
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill(); ctx.stroke();
        continue;
      }
      if (p.kind === "confetti") {
        p.vy += 0.02; p.vx *= 0.995;
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a);
        ctx.fillStyle = p.color; ctx.fillRect(-p.r / 2, -p.r / 4, p.r, p.r / 2); ctx.restore();
        if (p.y > H + 20) particles.splice(i, 1);
        continue;
      }
      if (p.kind === "egg") {
        ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.a);
        ctx.fillStyle = p.color; ctx.beginPath(); ctx.ellipse(0, 0, p.r * 0.75, p.r, 0, 0, 6.283); ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,.8)"; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(-p.r * 0.7, 0); ctx.lineTo(p.r * 0.7, 0); ctx.stroke(); ctx.restore();
        if (p.y > H + 20) particles.splice(i, 1);
        continue;
      }
      if (p.kind === "bat") {
        drawBat(p);
        if (p.x < -60 || p.x > W + 60) particles.splice(i, 1);
        continue;
      }
      if (p.kind === "spark") {
        p.vy += 0.03; p.vx *= 0.98; p.vy *= 0.98; p.life -= p.decay;
        ctx.globalAlpha = Math.max(0, p.life);
        ctx.fillStyle = p.color; ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
        ctx.globalAlpha = 1;
        if (p.life <= 0) particles.splice(i, 1);
      }
    }
    requestAnimationFrame(frame);
  }
  document.addEventListener("visibilitychange", function () {
    var was = running;
    running = !document.hidden;
    if (running && !was) requestAnimationFrame(frame);
  });
  requestAnimationFrame(frame);
  window.addEventListener("pagehide", function () { clearInterval(batTimer); clearInterval(fwTimer); });
})();
