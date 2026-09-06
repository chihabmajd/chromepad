/* ChromePad touch client (vanilla JS). */
(() => {
  'use strict';

  const TAP_MAX_MS    = 200;
  const TAP_MAX_MOVE  = 10;    // px
  const DOUBLE_TAP_MS = 300;
  const DEAD_ZONE     = 0.08;
  const JOY_RADIUS    = 70;    // px
  const MAX_SPEED     = 16;    // px/frame at full tilt
  const SMOOTH        = 0.65;  // velocity smoothing (higher = snappier)
  const TRACKPAD_GAIN = 1.8;
  const SCROLL_STEP   = 14;    // px per wheel notch
  const VOLUME_STEP   = 16;    // px per volume step
  const VIBRATE_MS    = 20;
  const TYPE_FLUSH_MS = 240;
  const GUARD         = '​';  // zero-width guard char in the hidden field

  const pad        = document.getElementById('pad');
  const joystick   = document.getElementById('joystick');
  const joyStick   = joystick.querySelector('.joy-stick');
  const scrollEl   = document.getElementById('scroll');
  const volumeEl   = document.getElementById('volume');
  const volTrack   = document.getElementById('vol-track');
  const muteBtn    = document.getElementById('mute-btn');
  const statusEl   = document.getElementById('status');
  const statusText = document.getElementById('status-text');
  const hint       = document.getElementById('hint');
  const kbToggle   = document.getElementById('kb-toggle');
  const kbPill     = document.getElementById('kb-pill');
  const hiddenInput= document.getElementById('hidden-input');
  const settingsToggle = document.getElementById('settings-toggle');
  const settingsPanel  = document.getElementById('settings-panel');
  const settingsClose  = document.getElementById('settings-close');
  const sensSlider = document.getElementById('sensitivity');
  const sensValue  = document.getElementById('sens-value');
  const clipToggle = document.getElementById('clip-toggle');
  const clipPanel  = document.getElementById('clip-panel');
  const clipText   = document.getElementById('clip-text');
  const clipSend   = document.getElementById('clip-send');
  const clipPaste  = document.getElementById('clip-paste');
  const clipClose  = document.getElementById('clip-close');

  let mode = localStorage.getItem('chromepad.mode') === 'trackpad' ? 'trackpad' : 'joystick';

  // The QR URL carries ?k=<token>; the server rejects sockets without it.
  const qs = new URLSearchParams(location.search);
  const token = qs.get('k') || localStorage.getItem('chromepad.token') || '';
  if (qs.get('k')) localStorage.setItem('chromepad.token', token);

  let ws = null, wsReady = false, reconnectDelay = 500;
  let rtt = null, everOpen = false;

  function connect() {
    setStatus('reconnecting', 'connecting');
    ws = new WebSocket(`ws://${location.host}/ws?k=${encodeURIComponent(token)}`);
    ws.onopen = () => {
      wsReady = true; everOpen = true; reconnectDelay = 500;
      setStatus('connected', 'connected');
    };
    ws.onmessage = (ev) => handleServer(ev.data);
    ws.onclose = () => {
      wsReady = false;
      setStatus('reconnecting', everOpen ? 'reconnecting' : 'scan the QR again');
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.6, 5000);
    };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  }

  function send(obj) {
    if (wsReady) { try { ws.send(JSON.stringify(obj)); } catch (_) {} }
  }

  function setStatus(cls, text) {
    statusEl.className = 'status ' + cls;
    statusText.textContent = text;
  }
  function showLatency() {
    if (rtt != null && statusEl.classList.contains('connected')) {
      statusText.textContent = rtt + ' ms';
    }
  }

  function handleServer(data) {
    let m; try { m = JSON.parse(data); } catch (_) { return; }
    if (m.event === 'text_focus') {
      m.state ? onTextFocus() : offTextFocus();
    } else if (m.event === 'welcome') {
      keyboardAvailable = !!m.keyboard;
    } else if (m.event === 'pong') {
      rtt = Math.round(performance.now() - m.id);
      showLatency();
    }
  }
  let keyboardAvailable = true;

  // Latency ping + keepalive (keeps the phone Wi-Fi radio awake).
  setInterval(() => { if (wsReady) send({ t: 'ping', id: Math.round(performance.now()) }); }, 1000);

  let sensitivity = parseFloat(localStorage.getItem('chromepad.sensitivity'));
  if (!(sensitivity > 0)) sensitivity = 1;
  sensSlider.value = sensitivity;
  sensValue.textContent = sensitivity.toFixed(2);
  sensSlider.addEventListener('input', () => {
    sensitivity = parseFloat(sensSlider.value);
    sensValue.textContent = sensitivity.toFixed(2);
    localStorage.setItem('chromepad.sensitivity', String(sensitivity));
  });

  function vibrate() { if (navigator.vibrate) navigator.vibrate(VIBRATE_MS); }

  const padTouches = new Map();
  let joyActive = false;
  let joyId = null;
  let joyCenter = { x: 0, y: 0 };
  let touchStartX = 0, touchStartY = 0, touchStartT = 0;
  let moved = false;
  let twoFinger = false;
  let twoFingerT = 0;
  let dragMode = false;
  let lastTapT = 0;
  let targetVx = 0, targetVy = 0;
  let vx = 0, vy = 0;
  let accX = 0, accY = 0;
  let rafId = 0, lastFrame = 0;
  let lastTpX = 0, lastTpY = 0, tpAccX = 0, tpAccY = 0;

  function showJoystick(x, y) {
    joyCenter = { x, y };
    joystick.style.left = x + 'px';
    joystick.style.top = y + 'px';
    joyStick.style.transform = 'translate(0px, 0px)';
    joystick.classList.remove('hidden');
    void joystick.offsetWidth;
    joystick.classList.add('show');
    joyActive = true;
  }

  function hideJoystick() {
    joystick.classList.remove('show');
    joystick.classList.add('hidden');
    joyStick.style.transform = 'translate(0px, 0px)';
  }

  function frame(now) {
    const dt = Math.min(now - lastFrame, 50);
    lastFrame = now;
    const f = dt / 16.667;
    const k = 1 - Math.pow(1 - SMOOTH, f);        // framerate-independent smoothing
    vx += (targetVx - vx) * k;
    vy += (targetVy - vy) * k;
    accX += vx * f; accY += vy * f;               // sub-pixel accumulation
    const dx = Math.trunc(accX), dy = Math.trunc(accY);
    accX -= dx; accY -= dy;
    if (dx || dy) send({ t: 'm', dx, dy });
    rafId = joyActive ? requestAnimationFrame(frame) : 0;
  }
  function startSendLoop() {
    if (rafId) return;
    lastFrame = performance.now();
    rafId = requestAnimationFrame(frame);
  }
  function stopSendLoop() {
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
  }

  function resetGesture() {
    joyActive = false; joyId = null; twoFinger = false;
    dragMode = false; moved = false;
    targetVx = targetVy = vx = vy = accX = accY = 0;
    tpAccX = tpAccY = 0;
    hideJoystick();
    stopSendLoop();
  }

  function leftClick()  { send({ t: 'c', b: 'l' }); vibrate(); }
  function rightClick() { send({ t: 'c', b: 'r' }); vibrate(); }

  function onControl(e) { return e.target.closest('button'); }

  function padTouchStart(e) {
    if (onControl(e)) return;
    hint.classList.add('gone');
    const now = performance.now();
    for (const t of e.changedTouches) {
      padTouches.set(t.identifier, { startX: t.clientX, startY: t.clientY, startT: now });
    }
    const count = padTouches.size;

    if (count === 1) {
      const t = e.changedTouches[0];
      joyId = t.identifier;
      touchStartX = t.clientX; touchStartY = t.clientY; touchStartT = now;
      moved = false; twoFinger = false;
      if (now - lastTapT < DOUBLE_TAP_MS) {        // double-tap then hold = drag
        dragMode = true;
        send({ t: 'dn' });
      } else {
        dragMode = false;
      }
      if (mode === 'trackpad') {
        lastTpX = t.clientX; lastTpY = t.clientY;
        tpAccX = tpAccY = 0;
        joyActive = true;
      } else {
        showJoystick(touchStartX, touchStartY);
        startSendLoop();
      }
    } else if (count === 2 && !moved) {            // two-finger tap = right-click
      twoFinger = true;
      twoFingerT = now;
      targetVx = targetVy = vx = vy = 0;
      hideJoystick();
      if (dragMode) { send({ t: 'up' }); dragMode = false; }
    }
  }

  function trackpadMove(e) {
    if (twoFinger) return;
    let t = null;
    for (const ct of e.changedTouches) if (ct.identifier === joyId) { t = ct; break; }
    if (!t) return;
    const dx = t.clientX - lastTpX, dy = t.clientY - lastTpY;
    lastTpX = t.clientX; lastTpY = t.clientY;
    if (Math.hypot(t.clientX - touchStartX, t.clientY - touchStartY) > TAP_MAX_MOVE) moved = true;
    const g = TRACKPAD_GAIN * sensitivity;
    tpAccX += dx * g; tpAccY += dy * g;
    const ix = Math.trunc(tpAccX), iy = Math.trunc(tpAccY);
    tpAccX -= ix; tpAccY -= iy;
    if (ix || iy) send({ t: 'm', dx: ix, dy: iy });
  }

  function padTouchMove(e) {
    if (onControl(e)) return;
    if (mode === 'trackpad') { trackpadMove(e); return; }
    if (!joyActive || twoFinger) return;
    let t = null;
    for (const ct of e.changedTouches) if (ct.identifier === joyId) { t = ct; break; }
    if (!t) return;

    const dx = t.clientX - joyCenter.x;
    const dy = t.clientY - joyCenter.y;
    const dist = Math.hypot(dx, dy) || 0.0001;
    if (Math.hypot(t.clientX - touchStartX, t.clientY - touchStartY) > TAP_MAX_MOVE) moved = true;

    const clamped = Math.min(dist, JOY_RADIUS);
    joyStick.style.transform = `translate(${(dx / dist) * clamped}px, ${(dy / dist) * clamped}px)`;

    const mag = clamped / JOY_RADIUS;
    if (mag < DEAD_ZONE) {
      targetVx = targetVy = 0;
    } else {
      const norm = (mag - DEAD_ZONE) / (1 - DEAD_ZONE);
      const speed = Math.pow(norm, 1.8) * MAX_SPEED * sensitivity;
      targetVx = (dx / dist) * speed;
      targetVy = (dy / dist) * speed;
    }
  }

  function padTouchEnd(e) {
    if (onControl(e)) return;
    const now = performance.now();
    for (const t of e.changedTouches) padTouches.delete(t.identifier);

    if (twoFinger) {
      if (!moved && (now - twoFingerT) < TAP_MAX_MS * 2) {
        rightClick();
        moved = true;
      }
      if (padTouches.size === 0) resetGesture();
      return;
    }

    if (padTouches.size === 0) {
      const dt = now - touchStartT;
      if (dragMode) {
        send({ t: 'up' });
      } else if (!moved && dt < TAP_MAX_MS) {
        leftClick();
        lastTapT = now;
      }
      resetGesture();
    }
  }

  pad.addEventListener('touchstart', padTouchStart, { passive: false });
  pad.addEventListener('touchmove', padTouchMove, { passive: false });
  pad.addEventListener('touchend', padTouchEnd, { passive: false });
  pad.addEventListener('touchcancel', padTouchEnd, { passive: false });

  let scrollLastY = 0, scrollAccum = 0, scrollVel = 0, scrollLastT = 0, inertiaRAF = 0;

  function scrollStart(e) {
    e.stopPropagation();
    cancelAnimationFrame(inertiaRAF);
    scrollLastY = e.touches[0].clientY;
    scrollAccum = 0; scrollVel = 0;
    scrollLastT = performance.now();
  }
  function scrollMove(e) {
    e.stopPropagation(); e.preventDefault();
    const y = e.touches[0].clientY;
    const now = performance.now();
    const dy = y - scrollLastY;
    scrollLastY = y;
    const dt = now - scrollLastT; scrollLastT = now;
    if (dt > 0) scrollVel = dy / dt;
    scrollAccum += dy;
    emitScroll();
  }
  function emitScroll() {
    while (scrollAccum >= SCROLL_STEP) { send({ t: 'w', d: -1 }); scrollAccum -= SCROLL_STEP; }
    while (scrollAccum <= -SCROLL_STEP) { send({ t: 'w', d: 1 }); scrollAccum += SCROLL_STEP; }
  }
  function scrollEnd(e) {
    e.stopPropagation();
    let v = scrollVel * 16;
    if (Math.abs(v) < 2) return;
    function step() {
      scrollAccum += v;
      emitScroll();
      v *= 0.9;
      if (Math.abs(v) > 0.6) inertiaRAF = requestAnimationFrame(step);
    }
    inertiaRAF = requestAnimationFrame(step);
  }
  scrollEl.addEventListener('touchstart', scrollStart, { passive: false });
  scrollEl.addEventListener('touchmove', scrollMove, { passive: false });
  scrollEl.addEventListener('touchend', scrollEnd, { passive: false });
  scrollEl.addEventListener('touchcancel', scrollEnd, { passive: false });

  // Drag the volume track for level; tap the speaker button to mute.
  let volLastY = 0, volAccum = 0;
  function volStart(e) {
    e.stopPropagation();
    volLastY = e.touches[0].clientY;
    volAccum = 0;
  }
  function volMove(e) {
    e.stopPropagation(); e.preventDefault();
    const y = e.touches[0].clientY;
    volAccum += y - volLastY;
    volLastY = y;
    while (volAccum <= -VOLUME_STEP) { send({ t: 'vol', d: 1 });  volAccum += VOLUME_STEP; }
    while (volAccum >=  VOLUME_STEP) { send({ t: 'vol', d: -1 }); volAccum -= VOLUME_STEP; }
    if (volumeEl.classList.contains('muted')) volumeEl.classList.remove('muted');
  }
  volTrack.addEventListener('touchstart', volStart, { passive: false });
  volTrack.addEventListener('touchmove', volMove, { passive: false });
  volTrack.addEventListener('touchend', (e) => e.stopPropagation(), { passive: false });
  volTrack.addEventListener('touchcancel', (e) => e.stopPropagation(), { passive: false });

  muteBtn.addEventListener('click', (e) => {
    e.preventDefault();
    send({ t: 'mute' });
    volumeEl.classList.toggle('muted');
    vibrate();
  });

  // Guard char keeps the caret off position 0, so Android still emits
  // deleteContentBackward on an "empty" field.
  let composing = false;

  // One paste per word rather than per letter, sparing clipboard and network.
  let typeBuf = '';
  let typeTimer = 0;
  function flushText() {
    if (typeTimer) { clearTimeout(typeTimer); typeTimer = 0; }
    if (typeBuf) { send({ t: 'kt', v: typeBuf }); typeBuf = ''; }
  }
  function queueText(s) {
    if (!s) return;
    typeBuf += s;
    if (/[\s.,;:!?)\]}'"]$/.test(s)) { flushText(); return; }
    if (typeTimer) clearTimeout(typeTimer);
    typeTimer = setTimeout(flushText, TYPE_FLUSH_MS);
  }

  function primeField() { hiddenInput.value = GUARD; }

  function focusHidden() {
    primeField();
    hiddenInput.focus({ preventScroll: true });
    try { hiddenInput.setSelectionRange(GUARD.length, GUARD.length); } catch (_) {}
  }

  function onTextFocus() { showPill(); focusHidden(); }
  function offTextFocus() { hidePill(); hiddenInput.blur(); }
  function showPill() { kbPill.classList.remove('hidden'); }
  function hidePill() { kbPill.classList.add('hidden'); }

  hiddenInput.addEventListener('focus', () => { hidePill(); kbToggle.classList.add('active'); primeField(); });
  hiddenInput.addEventListener('blur', () => { flushText(); kbToggle.classList.remove('active'); });

  hiddenInput.addEventListener('compositionstart', () => { composing = true; });
  hiddenInput.addEventListener('compositionend', (e) => {
    composing = false;
    queueText(e.data);
    primeField();
    try { hiddenInput.setSelectionRange(GUARD.length, GUARD.length); } catch (_) {}
  });

  hiddenInput.addEventListener('beforeinput', (e) => {
    const it = e.inputType;
    if (it === 'insertCompositionText') return;
    if (composing) return;
    if (it === 'insertText' || it === 'insertReplacementText' || it === 'insertFromPaste') {
      queueText(e.data);
      e.preventDefault();
    } else if (it === 'deleteContentBackward' || it === 'deleteWordBackward' || it === 'deleteContentForward') {
      flushText();
      send({ t: 'kb' });
      e.preventDefault();
    } else if (it === 'insertLineBreak' || it === 'insertParagraph') {
      flushText();
      send({ t: 'ke' });
      e.preventDefault();
    }
  });

  // Hardware keyboards (keyCode != 229) get Enter/Backspace directly.
  hiddenInput.addEventListener('keydown', (e) => {
    if (e.keyCode === 229) return;
    if (e.key === 'Enter') { e.preventDefault(); send({ t: 'ke' }); }
    else if (e.key === 'Backspace') { e.preventDefault(); send({ t: 'kb' }); }
  });

  kbToggle.addEventListener('click', (e) => {
    e.preventDefault();
    if (document.activeElement === hiddenInput) hiddenInput.blur();
    else focusHidden();
  });
  kbPill.addEventListener('click', (e) => { e.preventDefault(); focusHidden(); });

  function openSettings()  { settingsPanel.classList.remove('hidden'); }
  function closeSettings() { settingsPanel.classList.add('hidden'); }
  settingsToggle.addEventListener('click', (e) => { e.preventDefault(); openSettings(); });
  settingsClose.addEventListener('click', (e) => { e.preventDefault(); closeSettings(); });

  const modeSeg = document.getElementById('mode-seg');
  function applyModeUI() {
    modeSeg.querySelectorAll('.seg-btn').forEach((b) =>
      b.classList.toggle('active', b.dataset.mode === mode));
  }
  modeSeg.addEventListener('click', (e) => {
    const b = e.target.closest('.seg-btn');
    if (!b) return;
    e.preventDefault();
    mode = b.dataset.mode;
    localStorage.setItem('chromepad.mode', mode);
    applyModeUI();
    resetGesture();
  });
  applyModeUI();

  function openClip()  { clipPanel.classList.remove('hidden'); setTimeout(() => clipText.focus(), 50); }
  function closeClip() { clipPanel.classList.add('hidden'); }
  function flashBtn(btn, msg) {
    const old = btn.textContent;
    btn.textContent = msg;
    setTimeout(() => { btn.textContent = old; }, 900);
  }
  clipToggle.addEventListener('click', (e) => { e.preventDefault(); openClip(); });
  clipClose.addEventListener('click', (e) => { e.preventDefault(); closeClip(); });
  clipSend.addEventListener('click', (e) => {
    e.preventDefault();
    const v = clipText.value;
    if (!v) return;
    send({ t: 'clip', v });
    vibrate();
    flashBtn(clipSend, 'Copied to PC ✓');
    setTimeout(closeClip, 750);
  });
  clipPaste.addEventListener('click', (e) => {
    e.preventDefault();
    const v = clipText.value;
    if (!v) return;
    send({ t: 'clippaste', v });
    vibrate();
    flashBtn(clipPaste, 'Pasted on PC ✓');
    setTimeout(closeClip, 750);
  });

  document.addEventListener('touchmove', (e) => {
    if (e.target.closest('.settings-panel, .clip-panel')) return;
    e.preventDefault();
  }, { passive: false });
  document.addEventListener('contextmenu', (e) => e.preventDefault());
  document.addEventListener('gesturestart', (e) => e.preventDefault());
  document.addEventListener('dblclick', (e) => e.preventDefault());

  connect();
})();
