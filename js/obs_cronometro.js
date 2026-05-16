(function() {
  console.log('[CRONOMETRO] Inicializando...');
  
  const cronometroDiv = document.getElementById('cronometro');
  const timerDiv = document.getElementById('timer');
  
  if (!cronometroDiv || !timerDiv) {
    console.error('[CRONOMETRO] Elementos não encontrados');
    return;
  }
  
  let timeRemaining = 180; // 3 minutos em segundos
  let isRunning = false;
  let intervalId = null;
  
  // Função para formatar o tempo em HH:MM:SS
  function formatTime(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }
  
  // Função para iniciar o cronômetro
  function startTimer() {
    if (isRunning) {
      console.log('[CRONOMETRO] Timer já está rodando');
      return;
    }
    
    isRunning = true;
    cronometroDiv.style.display = 'block';
    console.log('[CRONOMETRO] Timer iniciado');
    
    intervalId = setInterval(function() {
      if (timeRemaining > 0) {
        timeRemaining--;
        timerDiv.textContent = formatTime(timeRemaining);
        console.log(`[CRONOMETRO] Tempo restante: ${formatTime(timeRemaining)}`);
      } else {
        // Timer chegou ao fim
        clearInterval(intervalId);
        isRunning = false;
        timerDiv.textContent = formatTime(0);
        console.log('[CRONOMETRO] Timer finalizado');
        // Opcional: esconder o timer após terminar
        setTimeout(function() {
          cronometroDiv.style.display = 'none';
          timeRemaining = 180;
          timerDiv.textContent = formatTime(180);
        }, 3000);
      }
    }, 1000);
  }
  
  // Função para resetar o cronômetro
  function resetTimer() {
    if (intervalId) {
      clearInterval(intervalId);
    }
    isRunning = false;
    timeRemaining = 180;
    timerDiv.textContent = formatTime(180);
    cronometroDiv.style.display = 'none';
    console.log('[CRONOMETRO] Timer resetado');
  }
  
  // Função para pausar o cronômetro
  function pauseTimer() {
    if (intervalId) {
      clearInterval(intervalId);
    }
    isRunning = false;
    console.log('[CRONOMETRO] Timer pausado');
  }
  
  // Função para retomar o cronômetro
  function resumeTimer() {
    if (!isRunning) {
      startTimer();
    }
  }
  
  // Expõe as funções globalmente para serem chamadas via console ou eventos
  window.cronometroAPI = {
    start: startTimer,
    reset: resetTimer,
    pause: pauseTimer,
    resume: resumeTimer,
    setTime: function(seconds) {
      if (typeof seconds === 'number' && seconds >= 0) {
        timeRemaining = seconds;
        timerDiv.textContent = formatTime(timeRemaining);
        console.log(`[CRONOMETRO] Tempo definido para: ${formatTime(timeRemaining)}`);
      }
    },
    getTime: function() {
      return timeRemaining;
    }
  };
  
  // Adiciona listener para GET via URL com parâmetro ?action=start
  function handlePageLoad() {
    const params = new URLSearchParams(window.location.search);
    const action = params.get('action');
    const time = params.get('time');
    
    if (time) {
      try {
        const seconds = parseInt(time);
        if (!isNaN(seconds) && seconds >= 0) {
          timeRemaining = seconds;
          timerDiv.textContent = formatTime(timeRemaining);
        }
      } catch (e) {
        console.error('[CRONOMETRO] Erro ao parsear tempo:', e);
      }
    }
    
    if (action === 'start') {
      startTimer();
    }
  }
  
  // Carrega ações ao inicializar
  handlePageLoad();
  
  console.log('[CRONOMETRO] Inicializado. Use window.cronometroAPI.start() para iniciar');
})();
