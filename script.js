let allChannels = [];
let favorites = JSON.parse(localStorage.getItem('subcleaner_favs') || '[]');

async function init() {
    const status = await (await fetch('/api/auth/status')).json();
    if (!status.ok) {
        document.getElementById('login-section').style.display = 'block';
        return;
    }
    document.getElementById('app-section').style.display = 'block';
    loadChannels();
}

async function loadChannels() {
    const res = await fetch('/api/all-channels');
    allChannels = await res.json();
    const cache = JSON.parse(localStorage.getItem('analysis_cache') || '{}');
    allChannels.forEach(c => {
        if (cache[c.channelId]) c.lastUploadDate = cache[c.channelId];
        c.isFavorite = favorites.includes(c.channelId);
    });
    renderTabs();
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
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({channelId: c.channelId})
            });
            const data = await res.json();
            c.lastUploadDate = data.lastUploadDate;
        }));
        const cache = JSON.parse(localStorage.getItem('analysis_cache') || '{}');
        chunk.forEach(c => cache[c.channelId] = c.lastUploadDate);
        localStorage.setItem('analysis_cache', JSON.stringify(cache));
        updateStats();
        renderList();
        document.getElementById('progress-bar').style.width = `${((i+chunkSize)/pending.length)*100}%`;
    }
    alert("完了");
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
    const tab = document.querySelector('.tab.active').dataset.cat;
    const m = document.getElementById('slider-months').value;
    const limit = new Date(); limit.setMonth(limit.getMonth() - m);
    const container = document.getElementById('list-container');
    container.innerHTML = '';

    allChannels.filter(c => {
        const isOld = c.lastUploadDate !== 'pending' && (c.lastUploadDate === 'none' || new Date(c.lastUploadDate) < limit);
        if (tab === 'target') return isOld && !c.isFavorite && c.subscribers < 100000;
        if (tab === 'star') return c.isFavorite;
        if (tab !== 'all') return c.category === tab;
        return true;
    }).forEach(c => {
        const isT = c.lastUploadDate !== 'pending' && (c.lastUploadDate === 'none' || new Date(c.lastUploadDate) < limit) && !c.isFavorite && c.subscribers < 100000;
        const div = document.createElement('div');
        div.className = 'channel-item';
        div.innerHTML = `
            <i class="fas fa-star fav-btn ${c.isFavorite ? 'active' : ''}" onclick="toggleFav('${c.channelId}')"></i>
            <img src="${c.thumbnails}" onclick="window.open('https://youtube.com/channel/${c.channelId}', '_blank')">
            <div class="info">
                <div class="title">${c.title}</div>
                <div class="meta">${c.category} | 登録者:${c.subscribers.toLocaleString()} | 最終:${c.lastUploadDate.split('T')[0]}</div>
            </div>
            ${isT ? '<i class="fas fa-trash-alt" style="color:#f44336"></i>' : ''}
        `;
        container.appendChild(div);
    });
}

function toggleFav(id) {
    const c = allChannels.find(x => x.channelId === id);
    c.isFavorite = !c.isFavorite;
    favorites = allChannels.filter(x => x.isFavorite).map(x => x.channelId);
    localStorage.setItem('subcleaner_favs', JSON.stringify(favorites));
    updateStats(); renderList();
}

function renderTabs() {
    const container = document.getElementById('category-tabs');
    [...new Set(allChannels.map(c => c.category))].forEach(cat => {
        const t = document.createElement('div');
        t.className = 'tab'; t.dataset.cat = cat; t.innerText = cat;
        t.onclick = function() {
            document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
            this.classList.add('active'); renderList();
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
    if (!confirm(`${targets.length}件解除しますか？`)) return;
    const res = await fetch('/api/subscriptions/bulk-delete', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({subscriptionIds: targets.map(t => t.subscriptionId)})
    });
    const data = await res.json();
    alert(`成功:${data.success} 失敗:${data.fail}`);
    location.reload();
}

document.getElementById('btn-analyze').onclick = analyzeChannels;
document.getElementById('btn-delete').onclick = bulkDelete;
document.getElementById('slider-months').oninput = function() {
    document.getElementById('val-months').innerText = this.value;
    updateStats(); renderList();
};
init();
