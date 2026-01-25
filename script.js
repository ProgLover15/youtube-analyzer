let allChannels = [];
let favorites = JSON.parse(localStorage.getItem('subcleaner_favs') || '[]');

// 1. チャンネル一覧の取得
async function loadChannels() {
    const res = await fetch('/api/all-channels');
    allChannels = await res.json();
    
    // キャッシュ(LocalStorage)から過去の分析結果を復元
    const cache = JSON.parse(localStorage.getItem('analysis_cache') || '{}');
    allChannels.forEach(c => {
        if (cache[c.channelId]) c.lastUploadDate = cache[c.channelId];
        if (favorites.includes(c.channelId)) c.isFavorite = true;
    });

    renderTabs();
    renderList();
    updateStats();
}

// 2. 並列分析 (5件ずつ同時実行)
async function analyzeChannels() {
    const pending = allChannels.filter(c => c.lastUploadDate === 'pending');
    if (pending.length === 0) return alert("分析が必要なチャンネルはありません");

    document.getElementById('progress-container').style.display = 'block';
    const chunkSize = 5;
    let processed = 0;

    for (let i = 0; i < pending.length; i += chunkSize) {
        const chunk = pending.slice(i, i + chunkSize);
        await Promise.all(chunk.map(async (c) => {
            try {
                const res = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({channelId: c.channelId})
                });
                const data = await res.json();
                c.lastUploadDate = data.lastUploadDate;
            } catch (e) {
                c.lastUploadDate = 'none';
            }
        }));
        
        processed += chunk.length;
        document.getElementById('progress-bar').style.width = `${(processed / pending.length) * 100}%`;
        
        // ローカルストレージに途中経過を保存
        const cache = JSON.parse(localStorage.getItem('analysis_cache') || '{}');
        chunk.forEach(c => cache[c.channelId] = c.lastUploadDate);
        localStorage.setItem('analysis_cache', JSON.stringify(cache));
        
        renderList();
        updateStats();
    }
    alert("分析が完了しました！");
}

// 3. 表示ロジック
function renderList() {
    const activeTab = document.querySelector('.tab.active').dataset.cat;
    const monthsLimit = document.getElementById('slider-months').value;
    const container = document.getElementById('list-container');
    container.innerHTML = '';

    const limitDate = new Date();
    limitDate.setMonth(limitDate.getMonth() - monthsLimit);

    const filtered = allChannels.filter(c => {
        const isOld = c.lastUploadDate !== 'pending' && (c.lastUploadDate === 'none' || new Date(c.lastUploadDate) < limitDate);
        const isSafe = c.subscribers >= 100000 || c.isFavorite;
        
        if (activeTab === 'target') return isOld && !isSafe;
        if (activeTab === 'star') return c.isFavorite;
        if (activeTab !== 'all') return c.category === activeTab;
        return true;
    });

    filtered.forEach(c => {
        const item = document.createElement('div');
        item.className = 'channel-item';
        const isTarget = c.lastUploadDate !== 'pending' && (c.lastUploadDate === 'none' || new Date(c.lastUploadDate) < limitDate) && !c.isFavorite && c.subscribers < 100000;

        item.innerHTML = `
            <i class="fas fa-star fav-btn ${c.isFavorite ? 'active' : ''}" onclick="toggleFav('${c.channelId}')"></i>
            <img src="${c.thumbnails}" onclick="window.open('https://youtube.com/channel/${c.channelId}', '_blank')">
            <div class="info">
                <div class="title">${c.title} <span class="badge">${c.category}</span></div>
                <div class="meta">登録者: ${c.subscribers.toLocaleString()}人 | 動画: ${c.videoCount}本</div>
                <div class="meta">最終更新: ${c.lastUploadDate === 'pending' ? '未分析' : c.lastUploadDate.split('T')[0]}</div>
            </div>
            ${isTarget ? '<i class="fas fa-trash-alt" style="color:var(--err)"></i>' : ''}
        `;
        container.appendChild(item);
    });
}

// 星付け機能
function toggleFav(id) {
    const c = allChannels.find(x => x.channelId === id);
    c.isFavorite = !c.isFavorite;
    favorites = allChannels.filter(x => x.isFavorite).map(x => x.channelId);
    localStorage.setItem('subcleaner_favs', JSON.stringify(favorites));
    renderList();
}

// ジャンルタブの生成
function renderTabs() {
    const tabsContainer = document.getElementById('category-tabs');
    const categories = [...new Set(allChannels.map(c => c.category))];
    categories.forEach(cat => {
        const tab = document.createElement('div');
        tab.className = 'tab';
        tab.dataset.cat = cat;
        tab.innerText = cat;
        tab.onclick = function() {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            renderList();
        };
        tabsContainer.appendChild(tab);
    });
}

// 起動処理
document.addEventListener('DOMContentLoaded', async () => {
    const status = await (await fetch('/api/auth/status')).json();
    if (status.ok) {
        document.getElementById('app-section').style.display = 'block';
        loadChannels();
    } else {
        document.getElementById('login-section').style.display = 'block';
    }
});

document.getElementById('btn-analyze').onclick = analyzeChannels;
document.getElementById('slider-months').oninput = function() {
    document.getElementById('val-months').innerText = this.value;
    renderList();
};
