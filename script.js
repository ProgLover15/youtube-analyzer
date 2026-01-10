/**
 * SubCleaner - script.js
 * YouTube API ToS Compliance Version
 */

let allChannels = [];

// --- 共通ユーティリティ ---

// トースト通知を表示
const showToast = (msg) => {
    const t = document.getElementById('toast') || createToastElement();
    t.textContent = msg;
    t.style.visibility = 'visible';
    t.style.opacity = '1';
    setTimeout(() => {
        t.style.visibility = 'hidden';
        t.style.opacity = '0';
    }, 3000);
};

const createToastElement = () => {
    const t = document.createElement('div');
    t.id = 'toast';
    t.style.cssText = 'position:fixed; bottom:30px; right:30px; background:var(--card-color); padding:16px; border-radius:8px; border:1px solid var(--accent-color); visibility:hidden; opacity:0; transition:0.3s; z-index:9999;';
    document.body.appendChild(t);
    return t;
};

// ローディング表示
const showLoading = (text) => {
    const overlay = document.getElementById('loading-overlay');
    const txt = document.getElementById('progress-text');
    txt.textContent = text;
    overlay.style.display = 'flex';
};

const hideLoading = () => {
    document.getElementById('loading-overlay').style.display = 'none';
};

// --- API操作 ---

// チャンネル一覧取得
async function fetchChannels() {
    try {
        const res = await fetch('/api/all-channels');
        if (!res.ok) throw new Error('Failed to fetch');
        allChannels = await res.json();
        renderChannels();
        updateDashboard();
    } catch (e) {
        showToast('データの取得に失敗しました');
    }
}

// チャンネル分析（個別または一括）
async function analyzeChannels() {
    const targets = allChannels.filter(c => c.isSubscribed && c.lastUploadDate === 'pending');
    if (targets.length === 0) {
        showToast('分析が必要なチャンネルはありません');
        return;
    }

    for (let i = 0; i < targets.length; i++) {
        const c = targets[i];
        showLoading(`分析中 (${i + 1}/${targets.length}): ${c.title}`);
        
        try {
            const res = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channelId: c.channelId })
            }).then(r => r.json());
            
            c.lastUploadDate = res.lastUploadDate || 'none';
            renderChannels();
            updateDashboard();
        } catch (e) {
            console.error('Analysis failed for:', c.title);
        }
    }
    hideLoading();
    showToast('すべての分析が完了しました');
}

// 登録解除処理
async function bulkUnsubscribe() {
    const checkboxes = document.querySelectorAll('.channel-checkbox:checked');
    const ids = Array.from(checkboxes).map(cb => cb.value);
    
    if (!confirm(`${ids.length}件の登録を解除しますか？\nこの操作は取り消せません。`)) return;

    showLoading('登録解除を実行中...');
    try {
        const res = await fetch('/api/subscriptions/bulk-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subscriptionIds: ids })
        }).then(r => r.json());

        // 成功したものを反映
        allChannels.forEach(c => {
            if (ids.includes(c.subscriptionId)) c.isSubscribed = false;
        });

        showToast(`完了: 成功 ${res.successCount}件 / 失敗 ${res.failCount}件`);
        renderChannels();
        updateDashboard();
    } catch (e) {
        showToast('エラーが発生しました');
    } finally {
        hideLoading();
    }
}

// --- UIレンダリング ---

function renderChannels() {
    const container = document.getElementById('channel-items-container');
    if (!container) return;
    container.innerHTML = '';

    allChannels.forEach(c => {
        const item = document.createElement('div');
        item.style.cssText = `display:flex; align-items:center; padding:12px; border-bottom:1px solid var(--border-color); ${!c.isSubscribed ? 'opacity:0.5;' : ''}`;
        
        // 状態テキストの生成
        let statusText = '未分析';
        let statusColor = 'var(--secondary-text-color)';
        
        if (c.lastUploadDate !== 'pending') {
            if (c.lastUploadDate === 'none') {
                statusText = '投稿動画なし';
                statusColor = var(--error-color);
            } else {
                const lastDate = new Date(c.lastUploadDate);
                const diffDays = Math.floor((new Date() - lastDate) / (1000 * 60 * 60 * 24));
                statusText = `${diffDays}日前に投稿`;
                if (diffDays > 60) statusColor = 'var(--error-color)';
            }
        }

        item.innerHTML = `
            <input type="checkbox" class="channel-checkbox" value="${c.subscriptionId}" ${!c.isSubscribed ? 'disabled' : ''} style="margin-right:15px; width:18px; height:18px;">
            <img src="${c.thumbnails}" style="width:40px; height:40px; border-radius:50%; margin-right:15px;">
            <div style="flex-grow:1;">
                <div style="font-weight:bold;">${c.title}</div>
                <div style="font-size:0.8em; color:${statusColor};">${statusText}</div>
            </div>
        `;
        container.appendChild(item);
    });
}

function updateDashboard() {
    const subs = allChannels.filter(c => c.isSubscribed);
    document.getElementById('count-subscribed').textContent = subs.length;
    document.getElementById('count-pending').textContent = subs.filter(c => c.lastUploadDate === 'pending').length;
    
    const inactive = subs.filter(c => {
        if (c.lastUploadDate === 'pending' || c.lastUploadDate === 'none') return false;
        return (new Date() - new Date(c.lastUploadDate)) / (1000 * 60 * 60 * 24) > 60;
    }).length;
    document.getElementById('count-inactive').textContent = inactive;
}

// --- イベントリスナー設定 ---

document.addEventListener('DOMContentLoaded', async () => {
    // 認証状態の確認
    const authRes = await fetch('/api/auth/status');
    if (authRes.ok) {
        document.getElementById('login-section').style.display = 'none';
        document.getElementById('app-section').style.display = 'block';
        document.getElementById('logout-btn').style.display = 'block';
        fetchChannels();
    }

    // モーダル制御
    const setupModal = (btnId, modalId) => {
        const btn = document.getElementById(btnId);
        const modal = document.getElementById(modalId);
        if (btn && modal) {
            btn.onclick = () => modal.style.display = 'block';
        }
    };

    setupModal('btn-tos', 'modal-tos');
    setupModal('btn-privacy', 'modal-privacy');
    setupModal('open-privacy-link', 'modal-privacy');

    document.querySelectorAll('.close-modal').forEach(span => {
        span.onclick = () => {
            document.querySelectorAll('.modal').forEach(m => m.style.display = 'none');
        };
    });

    // ログアウト
    document.getElementById('logout-btn').onclick = () => {
        location.href = '/logout';
    };

    // 分析ボタン
    document.getElementById('bulk-analyze-btn').onclick = analyzeChannels;

    // 全選択
    document.getElementById('select-all-checkbox').onchange = (e) => {
        const cbs = document.querySelectorAll('.channel-checkbox:not(:disabled)');
        cbs.forEach(cb => cb.checked = e.target.checked);
        document.getElementById('bulk-unsubscribe-btn').disabled = !e.target.checked || cbs.length === 0;
    };

    // 個別選択時の解除ボタン制御
    document.getElementById('channel-items-container').onchange = () => {
        const checkedCount = document.querySelectorAll('.channel-checkbox:checked').length;
        document.getElementById('bulk-unsubscribe-btn').disabled = checkedCount === 0;
    };

    // 解除実行
    document.getElementById('bulk-unsubscribe-btn').onclick = bulkUnsubscribe;
});
