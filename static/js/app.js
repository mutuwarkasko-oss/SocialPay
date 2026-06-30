// SocialPay v9.1 — Enhanced PWA Install System

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js').then(reg => {
      // Check for updates every 30 minutes
      setInterval(() => reg.update(), 30 * 60 * 1000);
    }).catch(() => {});

    // Listen for ONLINE_RESTORED message from SW
    navigator.serviceWorker.addEventListener('message', e => {
      if (e.data?.type === 'ONLINE_RESTORED') {
        const bar = document.getElementById('network-error-bar');
        if (bar) bar.style.display = 'none';
        showToast('✅ Haɗin intanet ya dawo!', 'success');
      }
    });
  });
}

// ============================================================
// PWA INSTALL SYSTEM — Persistent, iOS-aware, re-shows after dismiss
// ============================================================
(function() {
  // Constants
  const PWA_KEY        = 'sp_pwa_dismissed_at';  // localStorage key
  const REDISPLAY_MS   = 2 * 60 * 60 * 1000;     // re-show 2 hours after dismiss
  const FIRST_DELAY_MS = 3500;                    // wait before first show

  let deferredPrompt = null;

  // --- Helpers ---
  function isStandalone() {
    return window.matchMedia('(display-mode: standalone)').matches ||
           window.navigator.standalone === true;
  }

  function isIOS() {
    return /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
  }

  function isSupportedBrowser() {
    // Chrome/Edge/Samsung on Android + Chrome on desktop fire beforeinstallprompt
    return 'BeforeInstallPromptEvent' in window ||
           /chrome|crios|edg/i.test(navigator.userAgent);
  }

  function shouldShowPrompt() {
    if (isStandalone()) return false;             // already installed
    const dismissedAt = localStorage.getItem(PWA_KEY);
    if (!dismissedAt) return true;               // never dismissed
    return Date.now() - parseInt(dismissedAt, 10) > REDISPLAY_MS;
  }

  function markDismissed() {
    localStorage.setItem(PWA_KEY, Date.now().toString());
  }

  // --- Inject banner HTML if not present (so it works on ALL pages) ---
  function ensureBannerExists() {
    if (document.getElementById('pwa-banner')) return;
    const div = document.createElement('div');
    div.id = 'pwa-banner';
    div.className = 'pwa-banner';
    div.style.display = 'none';
    div.innerHTML = `
      <div style="font-size:32px">📱</div>
      <div class="pwa-banner-text">
        <div class="pwa-banner-title">Install SocialPay</div>
        <div class="pwa-banner-sub">Add to Home Screen for quick access</div>
      </div>
      <button class="pwa-banner-btn" onclick="installPWA()">Install Now</button>
      <button class="pwa-banner-close" onclick="dismissPWA()">✕</button>`;
    document.body.appendChild(div);
  }

  // --- Inject iOS popup HTML ---
  function ensureIOSPopupExists() {
    if (document.getElementById('pwa-ios-popup')) return;
    const div = document.createElement('div');
    div.id = 'pwa-ios-popup';
    div.style.cssText = `
      display:none; position:fixed; bottom:0; left:0; right:0; z-index:9999;
      background:white; border-radius:20px 20px 0 0;
      padding:24px 20px 40px; box-shadow:0 -8px 32px rgba(0,0,0,0.18);
      font-family:-apple-system,BlinkMacSystemFont,sans-serif; text-align:center;
      animation: slide-up-ios 0.35s ease;`;
    div.innerHTML = `
      <style>@keyframes slide-up-ios{from{transform:translateY(100%)}to{transform:translateY(0)}}</style>
      <button onclick="dismissIOSPopup()" style="position:absolute;top:14px;right:18px;background:none;border:none;font-size:22px;cursor:pointer;color:#aaa">✕</button>
      <div style="font-size:48px;margin-bottom:10px">📲</div>
      <div style="font-size:17px;font-weight:800;color:#0A2463;margin-bottom:6px">Install SocialPay</div>
      <div style="font-size:13px;color:#555;margin-bottom:20px">Install this app on your iPhone for the best experience</div>
      <div style="background:#f5f5f7;border-radius:14px;padding:16px;text-align:left">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
          <div style="font-size:24px">1️⃣</div>
          <div style="font-size:13px;color:#333">Tap the <strong>Share</strong> button <span style="font-size:18px">⎦⬆⎡</span> at the bottom of Safari</div>
        </div>
        <div style="display:flex;align-items:center;gap:12px">
          <div style="font-size:24px">2️⃣</div>
          <div style="font-size:13px;color:#333">Scroll down and tap <strong>"Add to Home Screen"</strong> 📌</div>
        </div>
      </div>
      <div style="margin-top:14px;font-size:12px;color:#aaa">Works just like WhatsApp & Instagram on your device</div>`;
    document.body.appendChild(div);
  }

  // --- Show/hide banner ---
  function showBanner() {
    ensureBannerExists();
    const b = document.getElementById('pwa-banner');
    if (b) b.style.display = 'flex';
  }

  function showIOSPopup() {
    ensureIOSPopupExists();
    const p = document.getElementById('pwa-ios-popup');
    if (p) p.style.display = 'block';
  }

  // --- Public API ---
  window.installPWA = function() {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    deferredPrompt.userChoice.then(choice => {
      if (choice.outcome === 'accepted') {
        // Installed — never show again
        localStorage.setItem(PWA_KEY, (Date.now() + 365 * 24 * 60 * 60 * 1000).toString());
      }
      deferredPrompt = null;
      dismissPWA();
    });
  };

  window.dismissPWA = function() {
    const b = document.getElementById('pwa-banner');
    if (b) b.style.display = 'none';
    markDismissed();
  };

  window.dismissIOSPopup = function() {
    const p = document.getElementById('pwa-ios-popup');
    if (p) p.style.display = 'none';
    markDismissed();
  };

  // --- Android/Chrome: beforeinstallprompt ---
  window.addEventListener('beforeinstallprompt', function(e) {
    e.preventDefault();
    deferredPrompt = e;
    if (shouldShowPrompt()) {
      setTimeout(showBanner, FIRST_DELAY_MS);
    }
  });

  // --- iOS Safari fallback ---
  window.addEventListener('load', function() {
    if (isIOS() && !isStandalone() && shouldShowPrompt()) {
      setTimeout(showIOSPopup, FIRST_DELAY_MS + 500);
    }
  });

  // --- appinstalled: mark as done ---
  window.addEventListener('appinstalled', function() {
    localStorage.setItem(PWA_KEY, (Date.now() + 365 * 24 * 60 * 60 * 1000).toString());
    const b = document.getElementById('pwa-banner');
    if (b) b.style.display = 'none';
  });

})();

function showToast(msg, type='info') {
  const icons = {success:'✅',error:'❌',info:'ℹ️',warning:'⚠️'};
  let c = document.getElementById('toast-container');
  if (!c) { c=document.createElement('div'); c.id='toast-container'; c.className='toast-container'; document.body.appendChild(c); }
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<span>${icons[type]||'•'}</span><span>${msg}</span>`;
  c.appendChild(t);
  setTimeout(() => { t.style.opacity='0'; t.style.transform='translateY(20px)'; t.style.transition='all .3s'; setTimeout(()=>t.remove(),320); }, 3400);
}

function openModal(id) { const el=document.getElementById(id); if(el){el.classList.add('active');document.body.style.overflow='hidden';} }
function closeModal(id) { const el=document.getElementById(id); if(el){el.classList.remove('active');document.body.style.overflow='';} }
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) { e.target.classList.remove('active'); document.body.style.overflow=''; }
});

async function postForm(url, fd, btn) {
  const orig = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled=true; btn.innerHTML='<span class="spinner"></span>'; }

  // Check if offline before attempting
  if (!navigator.onLine) {
    if (btn) { btn.disabled=false; btn.innerHTML=orig; }
    showNetworkError();
    return null;
  }

  try {
    const res = await fetch(url, {method:'POST', body:fd, credentials:'same-origin'});
    if (res.status === 401) {
      showToast('Session expired. Redirecting to login...', 'warning');
      setTimeout(()=>location.href='/login', 1500);
      return null;
    }
    const data = await res.json();
    if (data.success) {
      if (data.message) showToast(data.message,'success');
      if (data.redirect) setTimeout(()=>location.href=data.redirect, 700);
    } else { showToast(data.message||'Error','error'); }
    return data;
  } catch(e) {
    showNetworkError();
    return null;
  }
  finally { if(btn){btn.disabled=false;btn.innerHTML=orig;} }
}

// v8: Network failure handling
function showNetworkError() {
  let el = document.getElementById('network-error-bar');
  if (!el) {
    el = document.createElement('div');
    el.id = 'network-error-bar';
    el.style.cssText = 'position:fixed;bottom:70px;left:0;right:0;background:#EF233C;color:white;padding:12px 16px;z-index:9999;display:flex;align-items:center;justify-content:space-between;font-size:13px;font-weight:700;box-shadow:0 -2px 12px rgba(0,0,0,0.2)';
    el.innerHTML = '<span>📵 No internet connection. Please check your network.</span><button onclick="retryConnection()" style="background:white;color:#EF233C;border:none;padding:6px 14px;border-radius:8px;font-weight:800;cursor:pointer">Retry</button>';
    document.body.appendChild(el);
  } else {
    el.style.display = 'flex';
  }
}

async function retryConnection() {
  try {
    const res = await fetch('/api/wallet', {method:'GET', credentials:'same-origin'});
    if (res.ok) {
      const el = document.getElementById('network-error-bar');
      if (el) el.style.display = 'none';
      showToast('Connection restored!', 'success');
    } else { showToast('Still offline...', 'warning'); }
  } catch { showToast('Still offline...', 'warning'); }
}

// v8: Monitor network status
window.addEventListener('offline', showNetworkError);
window.addEventListener('online', () => {
  const el = document.getElementById('network-error-bar');
  if (el) el.style.display = 'none';
  showToast('Connection restored!', 'success');
});

let balHidden = false;
function toggleBalance() {
  balHidden = !balHidden;
  document.querySelectorAll('.balance-amount,.chip-value').forEach(el=>el.style.filter=balHidden?'blur(10px)':'none');
  const eb = document.getElementById('eyeBtn');
  if (eb) eb.textContent = balHidden ? '🙈' : '👁️';
}

function copyText(text, msg) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(()=>showToast(msg||'Copied!','success'));
  } else {
    const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta);
    ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
    showToast(msg||'Copied!','success');
  }
}

async function lookupUser(uid, targetId) {
  const el=document.getElementById(targetId);
  if (!uid||uid.length<5){if(el)el.textContent='';return;}
  try {
    const res=await fetch('/api/user_lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:uid}),credentials:'same-origin'});
    const data=await res.json();
    if(el){el.textContent=data.found?`✅ ${data.name}`:'❌ Not found';el.style.color=data.found?'#06D6A0':'#EF233C';}
  } catch {}
}

async function updateNotifBadge() {
  try {
    const res=await fetch('/api/notif_count',{credentials:'same-origin'}); const data=await res.json();
    const el=document.getElementById('notif-badge');
    if(el){
      const total = (data.count||0) + (data.messages||0);
      if(total>0){el.textContent=total>9?'9+':total;el.style.display='flex';}
      else{el.style.display='none';}
    }
    // v8: show message alert banner if unread admin messages
    if(data.messages > 0) {
      let msgBanner = document.getElementById('msg-alert-banner');
      if (!msgBanner) {
        msgBanner = document.createElement('div');
        msgBanner.id = 'msg-alert-banner';
        msgBanner.style.cssText = 'background:linear-gradient(135deg,#0A2463,#3E92CC);color:white;padding:10px 16px;font-size:13px;font-weight:700;display:flex;align-items:center;gap:8px;cursor:pointer;';
        msgBanner.innerHTML = `<span>📩</span><span style="flex:1">You have ${data.messages} new message(s). Please check.</span><a href="/notifications" style="background:white;color:#0A2463;padding:4px 12px;border-radius:8px;font-size:12px;font-weight:800;text-decoration:none">View</a>`;
        const content = document.querySelector('.page-content,.admin-content');
        if (content) content.insertBefore(msgBanner, content.firstChild);
      }
    }
  } catch {}
}
if (document.getElementById('notif-badge')) { updateNotifBadge(); setInterval(updateNotifBadge,30000); }

document.addEventListener('DOMContentLoaded', () => {
  const path = location.pathname;
  document.querySelectorAll('.nav-item').forEach(item => {
    const href = item.getAttribute('href');
    if (href&&path===href) item.classList.add('active');
    else if (href&&href!=='/'&&path.startsWith(href)) item.classList.add('active');
  });
});

function togglePw(inputId, btn) {
  const inp=document.getElementById(inputId); if(!inp) return;
  if (inp.type==='password'){inp.type='text';btn.innerHTML='🙈';}
  else{inp.type='password';btn.innerHTML='👁️';}
}

function openImageFull(src) {
  let overlay=document.getElementById('img-modal-overlay');
  if (!overlay) {
    overlay=document.createElement('div'); overlay.id='img-modal-overlay'; overlay.className='img-modal-overlay';
    overlay.innerHTML=`<button class="img-modal-close" onclick="closeImageFull()">✕</button><img id="img-modal-img" src="" alt="Proof" onclick="event.stopPropagation()" style="max-width:100%;max-height:90vh;border-radius:12px">`;
    overlay.addEventListener('click',closeImageFull); document.body.appendChild(overlay);
  }
  document.getElementById('img-modal-img').src=src;
  overlay.classList.add('active'); document.body.style.overflow='hidden';
}
function closeImageFull() {
  const o=document.getElementById('img-modal-overlay'); if(o){o.classList.remove('active');document.body.style.overflow='';}
}

function openTelegram(tgUrl, webUrl) {
  const start=Date.now(); window.location.href=tgUrl;
  const timer=setTimeout(()=>{ if(Date.now()-start<2000) window.location.href=webUrl||'https://telegram.org/'; },1500);
  document.addEventListener('visibilitychange',function h(){if(document.hidden){clearTimeout(timer);document.removeEventListener('visibilitychange',h);}});
}

function closeBanner(){document.getElementById('announceWrap')?.remove();document.getElementById('bannerSpacer')?.remove();sessionStorage.setItem('sp_bc','1');}
if(sessionStorage.getItem('sp_bc')){document.getElementById('announceWrap')?.remove();document.getElementById('bannerSpacer')?.remove();}

// ============================================================
// SPIN WHEEL — Fixed v7
// Pointer (▼) is at TOP = -Math.PI/2
// Wheel slots are drawn starting from rotation offset
// winIdx from server = exact prize index that was credited
// Wheel always stops with that exact slot under the pointer
// Numbers on wheel update whenever admin changes prizes
// ============================================================
const SPIN_COLORS=['#FF6B6B','#4ECDC4','#45B7D1','#96CEB4','#FFEAA7','#DDA0DD','#98D8C8','#F7DC6F'];
let spinRunning=false;
let _currentRotation=0; // track rotation globally so re-spins continue smoothly

function initSpinWheel(prizes) {
  const canvas=document.getElementById('spin-canvas'); if(!canvas) return;
  const ctx=canvas.getContext('2d');
  const W=canvas.width=260; const H=canvas.height=260;
  const cx=W/2, cy=H/2, r=cx-8;
  const n=prizes.length;
  const arc=(Math.PI*2)/n;

  function drawWheel(rot) {
    ctx.clearRect(0,0,W,H);
    // Draw outer ring
    ctx.beginPath(); ctx.arc(cx,cy,r+6,0,Math.PI*2);
    ctx.fillStyle='#0A2463'; ctx.fill();

    prizes.forEach((p,i) => {
      const s=rot+i*arc;
      const e=s+arc;
      // Slice
      ctx.beginPath(); ctx.moveTo(cx,cy); ctx.arc(cx,cy,r,s,e); ctx.closePath();
      ctx.fillStyle=SPIN_COLORS[i%SPIN_COLORS.length]; ctx.fill();
      ctx.strokeStyle='white'; ctx.lineWidth=2.5; ctx.stroke();
      // Label — show the prize label (e.g. ₦100) from server prizes
      ctx.save();
      ctx.translate(cx,cy);
      ctx.rotate(s+arc/2);
      // Prize amount text — right-aligned toward edge
      ctx.textAlign='right';
      ctx.fillStyle='white';
      ctx.font='bold 12px Nunito,Arial';
      ctx.shadowColor='rgba(0,0,0,0.4)';
      ctx.shadowBlur=3;
      ctx.fillText(p.label, r-10, 5);
      ctx.restore();
    });

    // Center circle
    ctx.beginPath(); ctx.arc(cx,cy,26,0,Math.PI*2);
    ctx.fillStyle='white'; ctx.fill();
    ctx.beginPath(); ctx.arc(cx,cy,20,0,Math.PI*2);
    ctx.fillStyle='#0A2463'; ctx.fill();
    ctx.fillStyle='white'; ctx.font='bold 11px Arial';
    ctx.textAlign='center'; ctx.textBaseline='middle';
    ctx.shadowBlur=0;
    ctx.fillText('SP',cx,cy);
  }

  drawWheel(_currentRotation);

  // _spinWheel(winIdx, cb)
  // winIdx = the prize index the SERVER already credited to user
  // We rotate wheel so that slot winIdx ends up under the TOP pointer (▼)
  window._spinWheel=function(winIdx, cb) {
    if(spinRunning) return;
    spinRunning=true;

    // The pointer is at the TOP of the canvas = angle -Math.PI/2 (i.e. 270°)
    // Slot i occupies angles: [rotation + i*arc, rotation + (i+1)*arc]
    // Center of slot i is at: rotation + i*arc + arc/2
    // We want: rotation + winIdx*arc + arc/2 ≡ -Math.PI/2  (mod 2π)
    // So: targetRotation = -Math.PI/2 - winIdx*arc - arc/2

    const pointerAngle = -Math.PI/2; // top of wheel
    // Desired final rotation so winIdx slot center is at pointer
    const slotCenter = winIdx * arc + arc/2;
    const rawTarget = pointerAngle - slotCenter;
    // Normalise to [0, 2π)
    const normalised = ((rawTarget % (Math.PI*2)) + Math.PI*2) % (Math.PI*2);
    // Add multiple full spins (5-8) for visual effect, landing on exact spot
    const fullSpins = (5 + Math.floor(Math.random()*4)) * Math.PI*2;
    const currentNorm = ((_currentRotation % (Math.PI*2)) + Math.PI*2) % (Math.PI*2);
    // Extra to rotate from current normalised position to target
    let extra = normalised - currentNorm;
    if(extra <= 0) extra += Math.PI*2;
    const totalRotation = fullSpins + extra;

    const duration=4500;
    const startTime=performance.now();
    const startRot=_currentRotation;

    function animate(now) {
      const elapsed=now-startTime;
      const prog=Math.min(elapsed/duration, 1);
      // Ease out cubic — smooth deceleration
      const ease=1-Math.pow(1-prog, 4);
      _currentRotation=startRot+totalRotation*ease;
      drawWheel(_currentRotation);
      if(prog<1) {
        requestAnimationFrame(animate);
      } else {
        _currentRotation=startRot+totalRotation; // set exact final value
        drawWheel(_currentRotation);
        spinRunning=false;
        if(cb) cb();
      }
    }
    requestAnimationFrame(animate);
  };
}

async function doSpin(prizes) {
  const btn=document.getElementById('spin-btn');
  if(spinRunning) return;
  const cost=(typeof SPIN_COST!=='undefined')?SPIN_COST:50;
  if(btn){btn.disabled=true;btn.innerHTML='<span class="spinner"></span> Spinning...';}

  const fd=new FormData();
  const res=await postForm('/spin',fd,null);

  if(res && res.success!==undefined) {
    // Re-init wheel with latest prizes from server (in case admin changed them)
    const serverPrizes=(res.prizes&&res.prizes.length>0)?res.prizes:prizes;
    initSpinWheel(serverPrizes);

    // winIdx = exact index the server credited — wheel MUST stop here
    const winIdx=res.index!==undefined?res.index:0;

    window._spinWheel&&window._spinWheel(winIdx,()=>{
      setTimeout(()=>{
        if(btn){btn.disabled=false;btn.innerHTML='🎰 Spin Now!';}
        // Show the EXACT prize that server credited
        if(res.amount>0) {
          showToast(`🎉 You won ${res.prize}! +₦${res.amount.toLocaleString()}`, 'success');
        } else {
          showToast(`😔 Try Again! ₦${cost.toLocaleString()} spent.`, 'info');
        }
        // Reload after toast so balance updates
        setTimeout(()=>location.reload(), 2800);
      }, 600);
    });
  } else {
    if(btn){btn.disabled=false;btn.innerHTML='🎰 Spin Now!';}
  }
}

function toggleWdFields() {
  const c=document.getElementById('wd-curr')?.value; if(!c) return;
  document.getElementById('naira-banks').style.display=c==='naira'?'':'none';
  document.getElementById('crypto-banks').style.display=c==='dollar'?'':'none';
}
function onBankSel(){document.getElementById('bank-other-wrap').style.display=document.getElementById('wd-bank-sel')?.value==='OTHER'?'':'none';}
function onCryptoSel(){document.getElementById('crypto-other-wrap').style.display=document.getElementById('wd-crypto-sel')?.value==='OTHER'?'':'none';}
function buildBankInfo() {
  const c=document.getElementById('wd-curr')?.value;
  if(c==='naira'){
    const sel=document.getElementById('wd-bank-sel')?.value;
    const bank=sel==='OTHER'?document.getElementById('wd-bank-other')?.value.trim():sel;
    const acct=document.getElementById('wd-acct')?.value.trim();
    const nm=document.getElementById('wd-aname')?.value.trim();
    if(!bank||!acct||!nm){showToast('Fill all bank details','warning');return null;}
    return `Bank: ${bank}\nAccount: ${acct}\nName: ${nm}`;
  } else {
    const sel=document.getElementById('wd-crypto-sel')?.value;
    const w=sel==='OTHER'?document.getElementById('wd-crypto-other')?.value.trim():sel;
    const addr=document.getElementById('wd-addr')?.value.trim();
    const net=document.getElementById('wd-net')?.value;
    if(!w||!addr){showToast('Fill wallet details','warning');return null;}
    return `Wallet: ${w}\nAddress: ${addr}\nNetwork: ${net}`;
  }
}
async function doWithdraw() {
  const pin=document.getElementById('wd-pin')?.value||'';
  if(!pin||pin.length!==4){showToast('Please enter your 4-digit PIN','warning');return;}
  const fd=new FormData();
  fd.append('currency',document.getElementById('wd-curr')?.value||'naira');
  fd.append('amount',document.getElementById('wd-amt')?.value||'0');
  fd.append('pin',pin);
  const r=await postForm('/withdraw',fd,document.getElementById('wd-btn'));
  if(r?.success){closeModal('withdrawModal');setTimeout(()=>location.reload(),1400);}
}
async function doTransfer() {
  const fd=new FormData();
  fd.append('receiver_id',document.getElementById('tr-recv')?.value.trim());
  fd.append('amount',document.getElementById('tr-amt')?.value);
  fd.append('pin',document.getElementById('tr-pin')?.value);
  const r=await postForm('/transfer',fd,document.getElementById('tr-btn'));
  if(r?.success){closeModal('transferModal');setTimeout(()=>location.reload(),1400);}
}
async function doExchange() {
  const fd=new FormData();
  fd.append('from_currency',document.getElementById('ex-from')?.value);
  fd.append('amount',document.getElementById('ex-amt')?.value);
  const r=await postForm('/exchange',fd,document.getElementById('ex-btn'));
  if(r?.success){
    const prev=document.getElementById('ex-preview');
    if(prev) prev.style.display='none';
    closeModal('exchangeModal');
    setTimeout(()=>location.reload(),1400);
  }
}

// ============================================================
// PUSH NOTIFICATIONS — Web Push Subscription
// ============================================================
async function setupPushNotifications() {
  if (!('Notification' in window) || !('serviceWorker' in navigator) || !('PushManager' in window)) return;

  try {
    // Fetch VAPID public key
    const keyRes = await fetch('/api/vapid_public_key',{credentials:'same-origin'});
    const keyData = await keyRes.json();
    const vapidPublicKey = keyData.public_key;
    if (!vapidPublicKey || vapidPublicKey.length < 10) return;

    const reg = await navigator.serviceWorker.ready;

    // Check existing subscription
    let sub = await reg.pushManager.getSubscription();

    if (!sub) {
      // Request permission first
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') return;

      // Subscribe
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidPublicKey)
      });
    }

    // Save subscription to server
    await fetch('/api/save_push_sub', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sub.toJSON()),
      credentials: 'same-origin'
    });
  } catch (e) {
    // Push not available or denied — silent fail
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

// Auto-setup push after page load (only on user pages, not login)
if (document.getElementById('notif-badge')) {
  // User is logged in — setup push
  window.addEventListener('load', () => {
    setTimeout(setupPushNotifications, 3000); // delay to avoid blocking page load
  });
}
