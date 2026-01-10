let channels = [];

document.addEventListener('DOMContentLoaded', async () => {
    const auth = await fetch('/api/auth/status');
    if (auth.ok) {
        document.getElementById('login-section').style.display = 'none';
        document.getElementById('app-section').style.display = 'block';
        load();
    }
});

async function load() {
    const res = await fetch('/api/all-channels');
    channels = await res.json();
    render();
}

// 3. スライダー操作時にリアルタイム描画
document.getElementById('slider-months').oninput = (e) => {
    document.getElementById('val-months').textContent = e.target.value;
    render();
};

// 2. シークバー進捗付き分析
async function analyze() {
    const targets = channels.filter(c => c.lastUploadDate === 'pending');
    if (targets.length === 0) return alert('分析が必要なチャンネルはありません。');
    
    document.getElementById('progress-area').style.display = 'block';

    for (let i = 0; i < targets.length; i++) {
        const c = targets[i];
        document.getElementById('progress-text').textContent = `分析中 (${i+1}/${targets.length}): ${c.title}`;
        document.getElementById('progress-fill').style.width = `${((i+1)/targets.length)*100}%`;

        const res = await fetch('/api/analyze', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({channelId: c.channelId})
        }).then(r => r.json());
        
        c.lastUploadDate = res.lastUploadDate;
        render(); // 1件ごとに結果を画面に反映
    }
    document.getElementById('progress-area').style.display = 'none';
    alert('分析が完了しました。');
}

function render() {
    const threshold = parseInt(document.getElementById('slider-months').value);
    const container = document.getElementById('list-container');
    container.innerHTML = '';
    let targetCount = 0;
    const now = new Date();

    channels.forEach(c => {
        let isInactive = false;
        let info = '未分析';

        if (c.lastUploadDate && c.lastUploadDate !== 'pending') {
            if (c.lastUploadDate === 'none') {
                info = '投稿動画なし';
                isInactive = true;
            } else {
                const lastDate = new Date(c.lastUploadDate);
                const diffMonths = (now.getFullYear() - lastDate.getFullYear()) * 12 + (now.getMonth() - lastDate.getMonth());
                info = `${diffMonths}ヶ月前の投稿`;
                if (diffMonths >= threshold) isInactive = true;
            }
        }

        if (isInactive && c.isSubscribed) targetCount++;

        const el = document.createElement('div');
        el.className = 'channel-item';
        el.style.opacity = c.isSubscribed ? '1' : '0.4';
        el.innerHTML = `
            <input type="checkbox" class="cb" value="${c.subscriptionId}" ${isInactive && c.isSubscribed ? 'checked' : ''} ${!c.isSubscribed ? 'disabled' : ''} style="width:18px;height:18px;margin-right:15px">
            <img src="${c.thumbnails}">
            <div style="flex:1">
                <div style="font-weight:bold">${c.title}</div>
                <div style="font-size:0.85em; color:var(--sec)">${info}</div>
            </div>
        `;
        container.appendChild(el);
    });

    document.getElementById('count-total').textContent = channels.length;
    document.getElementById('count-target').textContent = targetCount;
    document.getElementById('btn-delete').disabled = targetCount === 0;
}

// 4. 一括解除実行
async function bulkDelete() {
    const ids = Array.from(document.querySelectorAll('.cb:checked')).map(cb => cb.value);
    if (!confirm(`${ids.length}件のチャンネル登録を解除します。よろしいですか？`)) return;

    const btn = document.getElementById('btn-delete');
    btn.disabled = true;
    btn.textContent = '解除中...';

    const res = await fetch('/api/subscriptions/bulk-delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({subscriptionIds: ids})
    }).then(r => r.json());

    alert(`完了: ${res.successCount}件成功 / ${res.failCount}件失敗`);
    
    // UI反映
    channels.forEach(c => { if (ids.includes(c.subscriptionId)) c.isSubscribed = false; });
    btn.textContent = '選択したチャンネルを解除';
    render();
}

document.getElementById('btn-analyze').onclick = analyze;
document.getElementById('btn-delete').onclick = bulkDelete;
document.getElementById('btn-logout').onclick = () => location.href = '/logout';
