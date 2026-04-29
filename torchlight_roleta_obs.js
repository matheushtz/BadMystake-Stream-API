// Roleta OBS -- nova versão com gradiente cônico e polling do servidor
(function(){
  console.log('[ROLETA] Inicializando...');

  const wheel = document.getElementById('wheel');
  const labelsContainer = document.getElementById('labels');
  const center = document.getElementById('center');
  const wrapper = document.getElementById('wrapper');

  if (!wheel || !labelsContainer || !center || !wrapper) {
    console.error('[ROLETA] Elementos não encontrados', { wheel, labelsContainer, center, wrapper });
    return;
  }

  const values = [50, 75, 100, 125, 200, 300];
  const weights = [22, 22, 22, 22, 8, 4];
  const colors = ['#ff4d4d', '#4da6ff', '#4dff88', '#ffd24d', '#b84dff', '#ff944d'];
  const total = weights.reduce((a, b) => a + b, 0);

  const slices = [];
  const gradientParts = [];
  let current = 0;

  weights.forEach((weight, index) => {
    const angle = (weight / total) * 360;
    const start = current;
    const end = current + angle;
    const mid = (start + end) / 2;

    gradientParts.push(`${colors[index]} ${start}deg ${end}deg`);
    slices.push({ start, end, mid, value: values[index] });

    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = values[index];
    labelsContainer.appendChild(label);

    current = end;
  });

  wheel.style.background = `conic-gradient(from -90deg, ${gradientParts.join(',')})`;
  console.log('[ROLETA] Gradiente aplicado, slices:', slices.length);

  function layoutLabels() {
    const width = wheel.clientWidth;
    const height = wheel.clientHeight;
    if (!width || !height) {
      return;
    }

    const centerX = width / 2;
    const centerY = height / 2;
    const labelRadius = Math.min(width, height) * 0.37;

    labelsContainer.querySelectorAll('.label').forEach(function(label, index) {
      const slice = slices[index];
      const angleRad = ((slice.mid - 180) * Math.PI) / 180;
      const x = centerX + labelRadius * Math.cos(angleRad);
      const y = centerY + labelRadius * Math.sin(angleRad);

      label.style.left = `${x}px`;
      label.style.top = `${y}px`;
      label.style.transform = 'translate(-50%, -50%)';
    });
  }

  let rotation = 0;
  let lastTick = 0;
  let isSpinning = false;
  const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

  function tick() {
    try {
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.frequency.value = 1000;
      gain.gain.value = 0.02;
      osc.start();
      osc.stop(audioCtx.currentTime + 0.02);
    } catch (e) {}
  }

  function easeOut(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function spin() {
    if (isSpinning) return;
    isSpinning = true;

    const spins = 6 * 360;
    const extra = Math.random() * 360;
    const totalSpin = spins + extra;

    const duration = 4000;
    let start = null;

    function animate(ts) {
      if (!start) start = ts;

      let p = (ts - start) / duration;
      if (p > 1) p = 1;

      const eased = easeOut(p);
      const currentRot = rotation + totalSpin * eased;

      wheel.style.transform = `rotate(${currentRot}deg)`;

      const pointerAngle = (450 - currentRot) % 360;
      const normalizedPointer = pointerAngle < 0 ? pointerAngle + 360 : pointerAngle;
      const slice = slices.find(function(s) {
        return normalizedPointer >= s.start && normalizedPointer < s.end;
      }) || slices[slices.length - 1];

      if (slice) {
        center.innerHTML = `${slice.value}<br>FE`;
      }

      if (Math.floor(currentRot / 10) !== Math.floor(lastTick / 10)) {
        tick();
        lastTick = currentRot;
      }

      if (p < 1) {
        requestAnimationFrame(animate);
      } else {
        rotation += totalSpin;
        isSpinning = false;
        console.log('[ROLETA] Spin finalizado');
      }
    }

    requestAnimationFrame(animate);
  }

  let lastSeq = 0;
  const POLL_MS = 1000;
  const VISIBILITY_MS = 30000;
  let hideTimer = null;

  function getParam(name) {
    try {
      return new URLSearchParams(window.location.search).get(name);
    } catch (e) {
      return null;
    }
  }

  let rawFilter = (getParam('reward') || '').trim();
  if (!rawFilter) {
    rawFilter = (wrapper.getAttribute('data-default-reward') || '').trim();
  }

  const rewardFilter = rawFilter
    ? rawFilter.split(',').map(function(s) { return s.trim(); }).filter(Boolean)
    : [];

  function matchesFilter(event) {
    if (!rewardFilter.length) return true;

    const reward = event && event.reward ? event.reward : {};
    const id = String(reward.id || '').toLowerCase();
    const title = String(reward.title || '').toLowerCase();

    return rewardFilter.some(function(filter) {
      const normalized = filter.toLowerCase();
      if (!normalized) return false;
      if (normalized.length >= 8 && /[a-z0-9\-]/i.test(normalized)) {
        if (id === normalized || id.indexOf(normalized) !== -1) return true;
      }
      return title.indexOf(normalized) !== -1;
    });
  }

  function updateCenterDisplay() {
    const pointerAngle = (450 - rotation) % 360;
    const normalizedPointer = pointerAngle < 0 ? pointerAngle + 360 : pointerAngle;
    const slice = slices.find(function(s) {
      return normalizedPointer >= s.start && normalizedPointer < s.end;
    }) || slices[slices.length - 1];

    if (slice) {
      center.innerHTML = `${slice.value}<br>FE`;
    }
  }

  function showWheel(event) {
    console.log('[ROLETA] showWheel chamado', event);
    wrapper.style.display = 'block';
    updateCenterDisplay();
    layoutLabels();
    requestAnimationFrame(layoutLabels);
    spin();

    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(function() {
      wrapper.style.display = 'none';
    }, VISIBILITY_MS);
  }

  function poll() {
    fetch('/twitch/powerup/state', { cache: 'no-store' })
      .then(function(response) { return response.json(); })
      .then(function(payload) {
        if (!payload || typeof payload.seq === 'undefined') return;
        if (payload.seq !== lastSeq) {
          lastSeq = payload.seq;
          const event = payload.last_event || payload;
          if (!matchesFilter(event)) return;
          showWheel(event);
        }
      })
      .catch(function(error) {
        console.error('[ROLETA] Poll error:', error);
      });
  }

  window.addEventListener('resize', layoutLabels);
  setTimeout(layoutLabels, 0);
  setInterval(poll, POLL_MS);
  poll();
})();