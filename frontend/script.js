/* ============================================================
   MediQueue — Shared JavaScript Utilities
   ============================================================ */

const API_BASE = window.API_BASE_URL || 'http://localhost:8000';

/* ─── API Wrapper ─────────────────────────────────────────── */
async function api(path, method = 'GET', body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store'
    };
    const session = getSession();
    if (session && session.token) {
        opts.headers['Authorization'] = `Bearer ${session.token}`;
    }
    if (body !== null) opts.body = JSON.stringify(body);
    const res = await fetch(API_BASE + path, opts);
    const data = await res.json().catch(() => ({}));
    
    if (!res.ok) {
        if (res.status === 401) {
            clearSession();
            window.location.href = 'login.html';
            // Stop execution by throwing a silent error to prevent cascades
            throw new Error('Unauthorized');
        }
        throw new Error(data.detail || `Error ${res.status}`);
    }
    
    return data;
}

/* ─── Session ─────────────────────────────────────────────── */
function setSession(userId, role, token) {
    localStorage.setItem('mq_user_id', userId);
    localStorage.setItem('mq_role', role);
    if (token) localStorage.setItem('mq_token', token);
}
function getSession() {
    return {
        userId: localStorage.getItem('mq_user_id'),
        role: localStorage.getItem('mq_role'),
        token: localStorage.getItem('mq_token')
    };
}
function clearSession() {
    localStorage.removeItem('mq_user_id');
    localStorage.removeItem('mq_role');
    localStorage.removeItem('mq_token');
}

/* ─── Auth Guard ──────────────────────────────────────────── */
function requireRole(expectedRole) {
    const { userId, role } = getSession();

    // If not logged in at all
    if (!userId || !role) {
        clearSession();
        window.location.href = 'login.html';
        return;
    }

    // If logged in, but wrong role for this page
    if (role !== expectedRole) {
        // Do NOT aggressively redirect here!
        // If a user has both admin.html and doctor.html open, they share the same localStorage.
        // If they act in doctor.html, their role becomes 'doctor'.
        // If admin.html's auto-refresh then calls requireRole('admin'), we shouldn't redirect it
        // because that ruins the admin tab. 

        // Optional: show a prominent warning so the user knows this tab's role was overwritten
        if (document.readyState === 'complete') {
            showToast(`Role mismatch: Please log back in as ${expectedRole} to use this tab.`, 'warn');
        }
    }
}

/* ─── Toast Notifications ─────────────────────────────────── */
const TOAST_DURATION = 5000; // visible for 5 seconds

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = { success: '✅', error: '❌', info: 'ℹ️', warn: '⚠️' };
    const titles = { success: 'Success', error: 'Error', info: 'Info', warn: 'Warning' };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.style.setProperty('--toast-duration', TOAST_DURATION + 'ms');
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || '🔔'}</span>
        <span class="toast-body">
            <div class="toast-title">${titles[type] || type}</div>
            <div>${message}</div>
        </span>
        <button type="button" class="toast-close" aria-label="Dismiss">&times;</button>`;

    container.appendChild(toast);

    // Dismiss helper – adds exit animation then removes element smoothly
    function dismiss() {
        if (toast.classList.contains('toast-exit')) return;
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 400); // 400ms matches CSS animation
    }

    // Auto-dismiss after TOAST_DURATION
    const timer = setTimeout(dismiss, TOAST_DURATION);

    // Manual close button
    toast.querySelector('.toast-close').addEventListener('click', () => {
        clearTimeout(timer);
        dismiss();
    });
}

/* ─── Spinner (button loading state) ─────────────────────── */
function setLoading(btn, loading) {
    if (loading) {
        btn.disabled = true;
        btn._origText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner"></span> Loading…`;
    } else {
        btn.disabled = false;
        btn.innerHTML = btn._origText || btn.innerHTML;
    }
}

/* ─── Priority Label ──────────────────────────────────────── */
function priorityBadge(p) {
    const map = {
        1: ['badge-danger', '🚨 Emergency'],
        2: ['badge-warn', '👶 Child'],
        3: ['badge-accent', '👴 Senior'],
        4: ['badge-muted', '🧑 Normal'],
    };
    const [cls, label] = map[p] || ['badge-muted', 'Normal'];
    return `<span class="badge ${cls}">${label}</span>`;
}

/* ─── Format Minutes ──────────────────────────────────────── */
function fmtWait(mins) {
    if (mins === 0) return 'Next up';
    return `~${mins} min`;
}

/* ─── Logout ──────────────────────────────────────────────── */
function logout() {
    clearSession();
    window.location.href = 'login.html';
}

/* ─── Relative Time ───────────────────────────────────────── */
function relativeTime(ts) {
    if (!ts) return '';
    const now = Date.now();
    // Append 'Z' to force UTC parsing if missing
    const tsStr = ts.endsWith('Z') ? ts : ts + 'Z';
    const then = new Date(tsStr).getTime();
    const diffSec = Math.floor((now - then) / 1000);

    if (diffSec < 10) return 'Just now';
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin} min ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    
    // Fallback to locale date+time
    const d = new Date(tsStr);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' · ' + d.toLocaleDateString();
}

/* ─── Styled Confirm Modal ────────────────────────────────── */
(function _initConfirmModal() {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _buildModal);
    } else {
        _buildModal();
    }

    function _buildModal() {
        if (document.getElementById('mq-confirm-overlay')) return;

        const style = document.createElement('style');
        style.textContent = `
            #mq-confirm-overlay {
                position: fixed; inset: 0; z-index: 9999;
                background: rgba(0,0,0,.65);
                backdrop-filter: blur(6px);
                display: flex; align-items: center; justify-content: center;
                opacity: 0; pointer-events: none;
                transition: opacity .2s ease;
            }
            #mq-confirm-overlay.visible { opacity: 1; pointer-events: all; }
            #mq-confirm-box {
                background: var(--clr-surface, #1a1f2e);
                border: 1px solid var(--clr-border, rgba(255,255,255,.1));
                border-radius: 16px;
                padding: 2rem 2rem 1.5rem;
                max-width: 380px; width: 90%;
                box-shadow: 0 24px 64px rgba(0,0,0,.5);
                transform: translateY(12px);
                transition: transform .25s ease;
            }
            #mq-confirm-overlay.visible #mq-confirm-box { transform: translateY(0); }
            #mq-confirm-msg {
                font-size: .98rem; line-height: 1.55;
                color: var(--txt-100, #f0f2f5);
                margin-bottom: 1.5rem;
            }
            #mq-confirm-msg .confirm-icon { font-size: 2rem; display: block; margin-bottom: .65rem; }
            #mq-confirm-actions { display: flex; gap: .75rem; justify-content: flex-end; }
        `;
        document.head.appendChild(style);

        const overlay = document.createElement('div');
        overlay.id = 'mq-confirm-overlay';
        overlay.innerHTML = `
            <div id="mq-confirm-box">
                <div id="mq-confirm-msg"></div>
                <div id="mq-confirm-actions">
                    <button id="mq-confirm-cancel" class="btn btn-ghost btn-sm">Cancel</button>
                    <button id="mq-confirm-ok" class="btn btn-sm" style="background:rgba(255,80,80,.18);border:1px solid rgba(255,80,80,.4);color:#ff7b7b;">Confirm</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);
    }
})();

function showConfirm(message, icon = '⚠️') {
    return new Promise((resolve) => {
        const overlay = document.getElementById('mq-confirm-overlay');
        const msgEl = document.getElementById('mq-confirm-msg');
        const okBtn = document.getElementById('mq-confirm-ok');
        const cancelBtn = document.getElementById('mq-confirm-cancel');
        if (!overlay) { resolve(window.confirm(message)); return; }

        msgEl.innerHTML = `<span class="confirm-icon">${icon}</span>${message}`;
        overlay.classList.add('visible');

        function cleanup(result) {
            overlay.classList.remove('visible');
            okBtn.removeEventListener('click', onOk);
            cancelBtn.removeEventListener('click', onCancel);
            overlay.removeEventListener('click', onBgClick);
            resolve(result);
        }
        function onOk() { cleanup(true); }
        function onCancel() { cleanup(false); }
        function onBgClick(e) { if (e.target === overlay) cleanup(false); }

        okBtn.addEventListener('click', onOk);
        cancelBtn.addEventListener('click', onCancel);
        overlay.addEventListener('click', onBgClick);
    });
}

/* ─── Count-up Animation ──────────────────────────────────── */
function animateCount(el, target, duration = 600) {
    const start = parseInt(el.textContent) || 0;
    if (start === target) return;
    const startTime = performance.now();
    function step(now) {
        const progress = Math.min((now - startTime) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
        el.textContent = Math.round(start + (target - start) * eased);
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}


/* ─── WebSocket Manager ────────────────────────────────────── */
class MQWebSocketManager {
    constructor() {
        this.ws = null;
        this.reconnectTimer = null;
        this.connect();
    }

    connect() {
        const session = getSession();
        let token = session && session.token ? session.token : null;
        if (window.location.pathname.indexOf('display.html') !== -1) {
            token = 'display';
        }
        if (!token) return;

        // Use ws:// for http, wss:// for https
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        // API_BASE might be 'http://localhost:8000', we extract host
        const url = API_BASE.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws?token=' + token;
        
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            console.log('[WebSocket] Connected');
            if (this.reconnectTimer) {
                clearInterval(this.reconnectTimer);
                this.reconnectTimer = null;
            }
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'update') {
                    // Trigger global event so pages can refresh their data
                    window.dispatchEvent(new Event('mq-update'));
                }
            } catch (e) {
                console.error('[WebSocket] Failed to parse message', e);
            }
        };

        this.ws.onclose = () => {
            console.log('[WebSocket] Disconnected. Reconnecting in 5s...');
            if (!this.reconnectTimer) {
                this.reconnectTimer = setTimeout(() => this.connect(), 5000);
            }
        };

        this.ws.onerror = (err) => {
            console.error('[WebSocket] Error', err);
            this.ws.close();
        };
    }
}

// Auto-initialize if logged in (except login page)
if (window.location.pathname.indexOf('login.html') === -1) {
    window.mqSocket = new MQWebSocketManager();
}
