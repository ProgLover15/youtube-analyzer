let allChannels = [];
let favorites = JSON.parse(localStorage.getItem('subcleaner_favs') || '[]');

async function init() {
    try {
        const res = await fetch('/api/auth/status');
        if (!res.ok) throw new Error("Auth check failed");
        const status = await res.json();
        
        if (!status.ok) {
            document.getElementById('login-section').style.display = 'block';
            return;
        }
        document.getElementById('app-section').style.display = 'block';
        loadChannels();
    } catch (e) {
        console.error("Init Error:", e);
        // 通信エラーやセッション切れの場合はログインを促す
        document.getElementById('login-section').style.display = 'block';
    }
}

async function loadChannels() {
    const res = await fetch('/api/all-channels');
    if (res.status === 401) return location.href = '/login'; // セッション切れ対策
    
    allChannels = await res.json();
    const cache = JSON.parse(localStorage.getItem('analysis_cache') || '{}');
    allChannels.forEach(c => {
        if (cache[c.channelId]) c.lastUploadDate = cache[c.channelId];
        c.isFavorite = favorites.includes(c.channelId);
    });
    renderTabs();
    setupTabEvents();
    renderList();
    updateStats();
}

function setupTabEvents() {
    document.querySelectorAll('.tabs .tab').forEach(tab => {
        tab.onclick = function() {
            document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
            this.classList.add('active');
            renderList();
        };
    });
}

async function analyzeChannels() {
    const pending = allChannels.filter(c => c.lastUploadDate === 'pending');
    if (!pending.length) return alert("分析対象がありません");
    
    document.getElementById('progress-container').style.display = 'block';
    const chunkSize = 5;
    
    for (let i = 0; i < pending.length; i += chunkSize) {
        const chunk = pending.slice(i, i + chunkSize);
        
        await Promise.all(chunk.map(async (c) => {
            try {
                const res = await fetch('/api/analyze', {
                    method: 'POST', 
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({channelId: c.channelId})
                });
                
                if (res.status === 429) {
                    // 負荷制限(Rate Limit)がかかった場合、少し待機して再試行
                    await new Promise(r => setTimeout(r, 1000));
                    return analyzeChannels(); // 簡易的なリトライ
                }

                const data = await res.json();
                c.lastUploadDate = data.lastUploadDate || 'none';
            } catch (e) {
                c.lastUploadDate = 'none';
            }
        }));

        // APIを労わるためのマイクロウェイト(200ms)
        await new Promise(r => setTimeout(r, 200));

        const cache = JSON.parse(localStorage.getItem('analysis_cache') || '{}');
        chunk.forEach(c => cache[c.channelId] = c.lastUploadDate);
        localStorage.setItem('analysis_cache', JSON.stringify(cache));
        
        updateStats();
        renderList();
        document.getElementById('progress-bar').style.width = `${((i + chunkSize) / pending.length) * 100}%`;
    }
    alert("全チャンネルの分析が完了しました。リストを確認してください。");
}

function updateStats() {
    const m = document.getElementById('slider-months').value;
    const limit = new Date(); limit.setMonth(limit.getMonth() - m);
    document.getElementById('stat-total').innerText = allChannels.length;
    
    const targets = allChannels.filter(c => {
        const isOld = c.lastUploadDate !== 'pending' && (c.lastUploadDate === 'none' || new Date(c.lastUploadDate) < limit);
        return isOld && !c.isFavorite && c.subscribers < 100000;
    });
    
    document.getElementById('stat-target').innerText = targets.length;
    document.getElementById('btn-delete').style.display = targets.length ? 'inline-block' : 'none';
}

function renderList() {
    const activeTabElement = document.querySelector('.tab.active');
    if (!activeTabElement) return;
    
    const tab = activeTabElement.dataset.cat;
    const m = document.getElementById('slider-months').value;
    const limit = new Date(); limit.setMonth(limit.getMonth() - m);
    const container = document.getElementById('list-container');
    container.innerHTML = '';

    const filtered = allChannels.filter(c => {
        const isOld = c.lastUploadDate !== 'pending' && (c.lastUploadDate === 'none' || new Date(c.lastUploadDate) < limit);
        const isTarget = isOld && !c.isFavorite && c.subscribers < 100000;

        if (tab === 'target') return isTarget;
        if (tab === 'star') return c.isFavorite;
        if (tab === 'all') return true;
        return c.category === tab;
    });

    if (filtered.length === 0) {
        container.innerHTML = '<div style="padding:20px; text-align:center; color:#666;">表示するチャンネルがありません</div>';
        return;
    }

    filtered.forEach(c => {
        const isOld = c.lastUploadDate !== 'pending' && (c.lastUploadDate === 'none' || new Date(c.lastUploadDate) < limit);
        const isTarget = isOld && !c.isFavorite && c.subscribers < 100000;
        
        const div = document.createElement('div');
        div.className = 'channel-item';
        div.innerHTML = `
            <i class="fas fa-star fav-btn ${c.isFavorite ? 'active' : ''}" onclick="toggleFav('${c.channelId}')"></i>
            <img src="${c.thumbnails}" onclick="window.open('https://youtube.com/channel/${c.channelId}', '_blank')">
            <div class="info">
                <div class="title">${c.title}</div>
                <div class="meta">${c.category} | 登録者:${c.subscribers.toLocaleString()}人 | 最終投稿:${c.lastUploadDate === 'pending' ? '未分析' : c.lastUploadDate.split('T')[0]}</div>
            </div>
            ${isTarget ? '<i class="fas fa-trash-alt" style="color:#f44336; margin-left: 10px;"></i>' : ''}
        `;
        container.appendChild(div);
    });
}

function toggleFav(id) {
    const c = allChannels.find(x => x.channelId === id);
    if (!c) return;
    c.isFavorite = !c.isFavorite;
    favorites = allChannels.filter(x => x.isFavorite).map(x => x.channelId);
    localStorage.setItem('subcleaner_favs', JSON.stringify(favorites));
    updateStats(); 
    renderList();
}

function renderTabs() {
    const container = document.getElementById('category-tabs');
    // ジャンルタブの重複作成を防止
    const existingTabs = new Set([...container.querySelectorAll('.tab')].map(t => t.dataset.cat));
    const categories = [...new Set(allChannels.map(c => c.category))];
    
    categories.forEach(cat => {
        if (existingTabs.has(cat)) return;
        const t = document.createElement('div');
        t.className = 'tab'; 
        t.dataset.cat = cat; 
        t.innerText = cat;
        t.onclick = function() {
            document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
            this.classList.add('active'); 
            renderList();
        };
        container.appendChild(t);
    });
}

async function bulkDelete() {
    const m = document.getElementById('slider-months').value;
    const limit = new Date(); limit.setMonth(limit.getMonth() - m);
    const targets = allChannels.filter(c => {
        const isOld = c.lastUploadDate !== 'pending' && (c.lastUploadDate === 'none' || new Date(c.lastUploadDate) < limit);
        return isOld && !c.isFavorite && c.subscribers < 100000;
    });
    
    if (!confirm(`${targets.length}件のチャンネル登録を解除します。よろしいですか？`)) return;
    
    const res = await fetch('/api/subscriptions/bulk-delete', {
        method: 'POST', 
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({subscriptionIds: targets.map(t => t.subscriptionId)})
    });
    
    const data = await res.json();
    // 削除成功後はキャッシュをクリアしてリロード
    localStorage.removeItem('analysis_cache');
    alert(`完了しました（成功:${data.success} 失敗:${data.fail}）`);
    location.reload();
}

document.getElementById('btn-analyze').onclick = analyzeChannels;
document.getElementById('btn-delete').onclick = bulkDelete;
document.getElementById('slider-months').oninput = function() {
    document.getElementById('val-months').innerText = this.value;
    updateStats(); 
    renderList();
};

init();
