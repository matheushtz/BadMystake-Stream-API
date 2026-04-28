// Roleta OBS -- nova versão com gradiente cônico e polling do servidor
(function(){
  const wheel = document.getElementById("wheel");
  const labelsContainer = document.getElementById("labels");
  const center = document.getElementById("center");
  
  // configuração de valores, pesos e cores
  const values = [100, 200, 300, 400, 500, 1000];
  const weights = [1, 1, 1, 1, 1, 0.33];
  const colors = [
    "#ff4d4d",
    "#4da6ff",
    "#4dff88",
    "#ffd24d",
    "#b84dff",
    "#ff944d"
  ];
  
  const total = weights.reduce((a, b) => a + b, 0);
  
  let current = 0;
  let slices = [];
  let gradientParts = [];
  
  // construir gradiente e slices
  weights.forEach((w, i) => {
    let angle = (w / total) * 360;
    let start = current;
    let end = current + angle;
    
    gradientParts.push(`${colors[i]} ${start}deg ${end}deg`);
    slices.push({ start, end, value: values[i] });
    
    let mid = (start + end) / 2;
    const label = document.createElement("div");
    label.className = "label";
    label.innerText = values[i];
    
    let correctedAngle = mid;
    if (mid > 90 && mid < 270) {
      correctedAngle = mid + 180;
    }
    
    label.style.transform = `
      rotate(${mid}deg)
      translate(0, -140px)
      rotate(${-correctedAngle}deg)
    `;
    
    labelsContainer.appendChild(label);
    current = end;
  });
  
  wheel.style.background = `conic-gradient(${gradientParts.join(",")})`;
  
  // ===== animação =====
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
      gain.gain.value = 0.1;
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
      
      let eased = easeOut(p);
      let currentRot = rotation + totalSpin * eased;
      
      wheel.style.transform = `rotate(${currentRot}deg)`;
      
      let normalized = (currentRot % 360 + 360) % 360;
      
      let slice = slices.find(s =>
        normalized >= s.start && normalized < s.end
      );
      
      if (slice) {
        center.innerText = slice.value + "\nFE";
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
      }
    }
    
    requestAnimationFrame(animate);
  }
  
  // ===== polling do servidor =====
  let lastSeq = 0;
  const POLL_MS = 1000;
  const VISIBILITY_MS = 60000; // 1 minuto
  let hideTimer = null;
  
  function getParam(name){
    try{
      const params = new URLSearchParams(window.location.search);
      return params.get(name);
    }catch(e){return null}
  }
  
  let rawFilter = (getParam('reward')||'').trim();
  if(!rawFilter){
    try{
      const wrapper = document.getElementById('wrapper');
      if(wrapper) {
        const def = wrapper.getAttribute('data-default-reward');
        if(def) rawFilter = def.trim();
      }
    }catch(e){}
  }
  
  const rewardFilter = [];
  if(rawFilter){
    rawFilter.split(',').forEach(function(s){ 
      const trimmed = s.trim();
      if(trimmed) rewardFilter.push(trimmed);
    });
  }
  
  function matchesFilter(event){
    if(!rewardFilter || rewardFilter.length===0) return true;
    const r = (event && event.reward) ? event.reward : {};
    const id = (r.id||'').toString().toLowerCase();
    const title = (r.title||'').toString().toLowerCase();
    for(let i=0;i<rewardFilter.length;i++){
      const f = rewardFilter[i].toLowerCase();
      if(!f) continue;
      if(f.length >= 8 && /[a-z0-9\-]/i.test(f)){
        if(id === f || id.indexOf(f) !== -1) return true;
      }
      if(title.indexOf(f) !== -1) return true;
    }
    return false;
  }
  
  function showWheel(event){
    const wrapper = document.getElementById('wrapper');
    if(!wrapper) return;
    
    wrapper.style.display = 'block';
    spin();
    
    if(hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(function(){
      wrapper.style.display = 'none';
    }, VISIBILITY_MS);
  }
  
  function poll(){
    fetch('/twitch/powerup/state', {cache:'no-store'})
      .then(function(r){ return r.json(); })
      .then(function(j){
        if(!j || typeof j.seq === 'undefined') return;
        if(j.seq !== lastSeq){
          lastSeq = j.seq;
          const evt = j.last_event || j;
          if(!matchesFilter(evt)) return;
          showWheel(evt);
        }
      })
      .catch(function(e){ console.log('roleta poll error', e); });
  }
  
  setInterval(poll, POLL_MS);
  poll();
})();

