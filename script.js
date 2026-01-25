let allChannels = [];
let favorites = JSON.parse(localStorage.getItem('subcleaner_favs') || '[]');
let deletedChannels = JSON.parse(localStorage.getItem('subcleaner_deleted') || '[]');

async function init() {
    const res = await fetch('/api/auth/status');
    const status = await res.json();
    if (!status.ok) {
        document.getElementById('login-section').style.display = 'block';
        return;
    }
    document.getElementById('app-section').style.display = 'block';
    fetchUserInfo();
    loadChannels();
}

// ログイン中のユーザー情報を取得してヘッダーに反映
async function fetchUserInfo() {
    try {
        const res = await fetch('/api/user/info');
        if (res.ok) {
            const data = await res.json();
            if (data.ok) {
                document.getElementById('user-icon').src = data.icon;
                document.getElementById('user-icon').style.display = 'block';
                document.getElementById('user-name').innerText = data.name;
            }
        }
    } catch (e) {
        console.error("User info fetch failed");
    }
}

async function loadChannels() {
    const res = await fetch('/api/all-channels');
    allChannels = await res.json();
    const cache = JSON.parse(localStorage.getItem('analysis_cache') || '{}');
    allChannels.forEach(c => {
        if (cache[c.channelId]) c.lastUploadDate = cache[c.channelId];
        c.isFavorite = favorites.includes(c.channelId);
    });
    renderList();
    updateStats();
}

async function analyzeChannels() {
    const pending = allChannels.filter(c => c.lastUploadDate === 'pending');
    if (!pending.length) return alert("分析対象がありません");
    
    document.getElementById('progress-container').style.display = 'block';
    const chunkSize = 5;
    
    for (let i = 0; i < pending.length; i += chunkSize) {
        const chunk = pending.slice(i, i + chunkSize);
        await Promise.all(chunk.map(async (c) => {
            const res = await fetch('/api/analyze', {
                method: 'POST', 
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({channelId: c.channelId})
            });
            const data = await res.json();
            c.lastUploadDate = data.lastUploadDate;
        }));
        
        // キャッシュ更新
        const cache = JSON.parse(localStorage.getItem('analysis_cache') || '{}');
        chunk.forEach(c => cache[c.channelId] = c.lastUploadDate);
        localStorage.setItem('analysis_cache', JSON.stringify(cache));
        
        updateStats(); 
        renderList();
        document.getElementById('progress-bar').style.width = `${((i+chunkSize)/pending.length)*100}%`;
    }
    alert("完了しました");
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
    const activeTab = document.querySelector('.tab.active');
    const tab = activeTab ? activeTab.dataset.cat : 'all';
    const sortType = document.getElementById('sort-type').value;
    const m = document.getElementById('slider-months').value;
    const limit = new Date(); limit.setMonth(limit.getMonth() - m);
    const container = document.getElementById('list-container');
    container.innerHTML = '';

    // 表示するリストを選択（履歴か現行か）
    let list = (tab === 'deleted') ? deletedChannels : allChannels;

    // フィルタリング
    let filtered = list.filter(c => {
        if (tab === 'deleted') return true;
        const isOld = c.lastUploadDate !== 'pending' && (c.lastUploadDate === 'none' || new Date(c.lastUploadDate) < limit);
        if (tab === 'target') return isOld && !c.isFavorite && c.subscribers < 100000;
        if (tab === 'star') return c.isFavorite;
        return true;
    });

    // ソート処理
    filtered.sort((a, b) => {
        if (sortType === 'sub-desc') return b.subscribers - a.subscribers;
        if (sortType === 'sub-asc') return a.subscribers - b.subscribers;
        
        const dateA = new Date(a.lastUploadDate === 'none' || a.lastUploadDate === 'pending' ? 0 : a.lastUploadDate);
        const dateB = new Date(b.lastUploadDate === 'none' || b.lastUploadDate === 'pending' ? 0 : b.lastUploadDate);
        
        if (sortType === 'date-desc') return dateB - dateA;
        if (sortType === 'date-asc') return dateA - dateB;
        return 0;
    });

    if (filtered.length === 0) {
        container.innerHTML = '<div style="padding:20px; text-align:center; color:#666;">表示する項目がありません</div>';
        return;
    }

    filtered.forEach(c => {
        const div = document.createElement('div');
        div.className = 'channel-item';
        const isHistory = tab === 'deleted';
        div.innerHTML = `
            ${isHistory ? '' : `<i class="fas fa-star fav-btn ${c.isFavorite ? 'active' : ''}" onclick="toggleFav('${c.channelId}')"></i>`}
            <img src="${c.thumbnails}" onclick="window.open('https://youtube.com/channel/${c.channelId}', '_blank')">
            <div class="info">
                <div class="title">${c.title}</div>
                <div class="meta">登録者:${c.subscribers.toLocaleString()}人 | 最終投稿:${c.lastUploadDate.split('T')[0]}</div>
            </div>
            ${isHistory ? '<span style="color:#666; font-size:0.8em; border:1px solid #444; padding:2px 6px; border-radius:4px;">解除済み</span>' : ''}
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

async function bulkDelete() {
    const m = document.getElementById('slider-months').value;
    const limit = new Date(); limit.setMonth(limit.getMonth() - m);
    const targets = allChannels.filter(c => {
        const isOld = c.lastUploadDate !== 'pending' && (c.lastUploadDate === 'none' || new Date(c.lastUploadDate) < limit);
        return isOld && !c.isFavorite && c.subscribers < 100000;
    });

    if (!confirm(`${targets.length}件のチャンネル登録を解除しますか？`)) return;

    const res = await fetch('/api/subscriptions/bulk-delete', {
        method: 'POST', 
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({subscriptionIds: targets.map(t => t.subscriptionId)})
    });
    
    const data = await res.json();
    
    // 成功したものを履歴に追加
    deletedChannels = [...targets, ...deletedChannels].slice(0, 100);
    localStorage.setItem('subcleaner_deleted', JSON.stringify(deletedChannels));
    
    // キャッシュをリセットしてリロード
    localStorage.removeItem('analysis_cache');
    alert(`完了（成功:${data.success} 失敗:${data.fail}）`);
    location.reload();
}

// イベント設定
document.querySelectorAll('.tab').forEach(t => {
    t.onclick = function() {
        document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
        this.classList.add('active');
        renderList();
    };
});

document.getElementById('sort-type').onchange = renderList;
document.getElementById('btn-analyze').onclick = analyzeChannels;
document.getElementById('btn-delete').onclick = bulkDelete;
document.getElementById('slider-months').oninput = function() {
    document.getElementById('val-months').innerText = this.value;
    updateStats(); 
    renderList();
};

init();
