// ===== Elements =====
const startBtn     = document.getElementById('startBtn');
const confirmBtn   = document.getElementById('confirmBtn');
const emailInput   = document.getElementById('emailInput');
const transcriptEl = document.getElementById('transcript');
const orderBox     = document.getElementById('orderBox');
const totalBox     = document.getElementById('totalBox');
const statusEl     = document.getElementById('status');

// ===== Globals =====
let voices = [];
let chosenVoice = null;
let recognition = null;
let lastTranscript = "";
let SERVER_ITEMS = []; // from /api/menu

// --- Load menu (for TTS read-out) ---
async function loadMenu() {
  try {
    const res = await fetch('/api/menu', { cache: 'no-store' });
    SERVER_ITEMS = await res.json(); // [{name, price}, ...]
  } catch (e) {
    console.error('Failed to load menu', e);
    SERVER_ITEMS = [];
  }
}

// --- Voice (female if available) ---
function loadVoices() {
  voices = window.speechSynthesis.getVoices();
  chosenVoice =
    voices.find(v => /female|woman|Google UK English Female/i.test(
      `${v?.name || ''} ${v?.gender || ''}`
    )) ||
    voices.find(v => /Google.*English/i.test(v?.name || '')) ||
    voices[0] ||
    null;
}
loadVoices();
if (typeof speechSynthesis !== 'undefined' && speechSynthesis.onvoiceschanged !== undefined) {
  speechSynthesis.onvoiceschanged = loadVoices;
}

function speak(text, cb) {
  try {
    const u = new SpeechSynthesisUtterance(String(text || ''));
    if (chosenVoice) u.voice = chosenVoice;
    u.rate = 1;
    u.pitch = 1.05;
    u.onend = () => cb && cb();
    window.speechSynthesis.speak(u);
  } catch (e) {
    console.warn('TTS failed or blocked', e);
    cb && cb();
  }
}

// --- Speech recognition ---
function startListening() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    alert('Your browser does not support SpeechRecognition. Use Chrome desktop.');
    return;
  }
  recognition = new SR();
  recognition.lang = 'en-IN';
  recognition.interimResults = true;
  recognition.continuous = false;

  recognition.onresult = (ev) => {
    let txt = '';
    for (let i = 0; i < ev.results.length; i++) {
      txt += ev.results[i][0].transcript + ' ';
    }
    lastTranscript = (txt || '').trim();
    transcriptEl.textContent = lastTranscript;
  };
  recognition.onerror = (e) => {
    statusEl.textContent = 'Mic error: ' + (e?.error || 'unknown');
  };
  recognition.onend = () => {
    statusEl.textContent = 'Recognized. Click Confirm to place your order, or press Start again to retry.';
    confirmBtn.disabled = false;
  };

  recognition.start();
  statusEl.textContent = 'Listening... please say your order';
}

// --- Confetti burst ---
function confettiBurst() {
  if (typeof confetti !== 'function') return;
  const duration = 1800;
  const end = Date.now() + duration;
  const defaults = { startVelocity: 35, spread: 360, ticks: 60, zIndex: 1000 };

  const timer = setInterval(() => {
    const timeLeft = end - Date.now();
    if (timeLeft <= 0) return clearInterval(timer);
    const particleCount = 50 * (timeLeft / duration);
    confetti({ ...defaults, particleCount, origin: { x: Math.random() * 0.3 + 0.1, y: Math.random() * 0.2 + 0.2 } });
    confetti({ ...defaults, particleCount, origin: { x: Math.random() * 0.3 + 0.6, y: Math.random() * 0.2 + 0.2 } });
  }, 250);
}

// --- Start voice assistant ---
startBtn.addEventListener('click', async () => {
  statusEl.textContent = 'Preparing assistant...';
  confirmBtn.disabled = true;
  await loadMenu();

  const menuText = (SERVER_ITEMS.length > 0)
    ? SERVER_ITEMS.map(m => `${m.name} for rupees ${m.price}`).join(', ')
    : 'No items available today';

  setTimeout(() => {
    speak(`Welcome to Sunrise Bistro. Today's menu: ${menuText}. After the tone, please say your order.`, () => {
      startListening();
    });
  }, 300);
});

// --- Confirm & place order ---
confirmBtn.addEventListener('click', async () => {
  const email = (emailInput.value || '').trim();
  const transcript = (lastTranscript || '').trim();

  if (!transcript) {
    alert('Please speak your order first. Click Start.');
    return;
  }
  if (!email) {
    alert('Please enter your email.');
    emailInput.focus();
    return;
  }

  statusEl.textContent = 'Placing your order...';
  confirmBtn.disabled = true;

  try {
    const body = JSON.stringify({ transcript, email });

    const res = await fetch('/api/order', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body
    });

    const data = await res.json();

    if (!data || data.saved !== true) {
      statusEl.textContent = data?.error || 'No items detected. Please try again.';
      confirmBtn.disabled = false;
      return;
    }

    // Render order summary
    orderBox.textContent = (data.items || [])
      .map(i => `${i.name} × ${i.qty} — ₹${i.price * i.qty}`)
      .join('\n');
    totalBox.textContent = `Total: ₹${data.total}`;

    // Voice + confetti
    speak(`Thank you. Your order has been placed. The total is rupees ${data.total}. A confirmation email ${data.email_sent ? 'has been sent' : 'could not be sent'}. Goodbye.`);
    confettiBurst();

    statusEl.textContent = data.email_sent ? 'Order saved. Email sent.' : 'Order saved. Email failed to send.';
    emailInput.value = '';
    transcriptEl.textContent = '';
  } catch (err) {
    console.error(err);
    statusEl.textContent = 'Error placing order.';
    confirmBtn.disabled = false;
  } finally {
    setTimeout(() => (confirmBtn.disabled = false), 1500);
  }
});
