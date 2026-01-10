let allChannels = [];

const showToast = (msg) => {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
};

async function analyzeChannels() {
    const targets = allChannels.filter(c => c.isSubscribed && c.lastUploadDate === 'pending');
    if (targets.length === 0) return;

    const overlay = document.getElementById('loading-overlay');
    overlay.style.display = 'flex';
    
    for (let i = 0; i < targets.length; i++) {
        const c = targets[i];
        document.getElementById('progress-text').innerHTML = `分析中 (${i+1}/${targets.length})<br>${c.title}`;
        
        try {
            const res = await fetch('/api/analyze', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({channelId: c.channelId})
            }).then(r => r.json());
            
            c.lastUploadDate = res.lastUploadDate || 'none';
            renderChannels();
            updateDashboard();
        } catch (e) { console.error(e); }
    }
    overlay.style.display = 'none';
    showToast('分析が完了しました');
}

function renderChannels() {
    const container = document.getElementById('channel-items-container');
    container.innerHTML = '';
    allChannels.forEach(c => {
        const item = document.createElement('div');
        item.className = `channel-item ${!c.isSubscribed ? 'unsubscribed' : ''}`;
        
        let status = '分析待ち';
        if (c.lastUploadDate !== 'pending') {
            if (c.lastUploadDate === 'none') status = '投稿なし';
            else {
                const days = Math.floor((new Date() - new Date(c.lastUploadDate))/(1000*60*60*24));
                status = `${days}日前に投稿`;
            }
        }

        item.innerHTML = `
            <input type="checkbox" class="channel-checkbox" value="${c.subscriptionId}" ${!c.isSubscribed ? 'disabled' : ''}>
            <img src="${c.thumbnails}">
            <div style="flex-grow:1;"><strong>${c.title}</strong></div>
            <div style="font-size: 0.8em; color: var(--secondary-text-color);">${status}</div>
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
        return (new Date() - new Date(c.lastUploadDate))/(1000*60*60*24) > 60;
    }).length;
    document.getElementById('count-inactive').textContent = inactive;
}

document.addEventListener('DOMContentLoaded', async () => {
    const auth = await fetch('/api/auth/status');
    if (auth.ok) {
        document.getElementById('login-section').style.display = 'none';
        document.getElementById('app-section').style.display = 'block';
        document.getElementById('logout-btn').style.display = 'block';
        
        allChannels = await fetch('/api/all-channels').then(r => r.json());
        renderChannels();
        updateDashboard();
    }

    document.getElementById('bulk-analyze-btn').addEventListener('click', analyzeChannels);
    document.getElementById('logout-btn').addEventListener('click', () => location.href = '/logout');
    
    document.getElementById('select-all-checkbox').addEventListener('change', (e) => {
        document.querySelectorAll('.channel-checkbox:not(:disabled)').forEach(cb => cb.checked = e.target.checked);
        document.getElementById('bulk-unsubscribe-btn').disabled = !e.target.checked;
    });

    document.getElementById('channel-items-container').addEventListener('change', () => {
        const checked = document.querySelectorAll('.channel-checkbox:checked').length;
        document.getElementById('bulk-unsubscribe-btn').disabled = checked === 0;
    });

    document.getElementById('bulk-unsubscribe-btn').addEventListener('click', async () => {
        const ids = Array.from(document.querySelectorAll('.channel-checkbox:checked')).map(cb => cb.value);
        if (!confirm(`${ids.length}件の解除を実行しますか？`)) return;
        
        const res = await fetch('/api/subscriptions/bulk-delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({subscriptionIds: ids})
        }).then(r => r.json());
        
        allChannels.forEach(c => { if (ids.includes(c.subscriptionId)) c.isSubscribed = false; });
        showToast(`完了: 成功 ${res.successCount}件`);
        renderChannels();
        updateDashboard();
    });
});
