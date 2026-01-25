let channels = [];
const CONCURRENCY = 5; // 5件ずつ並列に分析（API制限を考慮した最適値）

document.addEventListener('DOMContentLoaded', async () => {
    // 認証状態の確認
    const auth = await fetch('/api/auth/status').then(r => r.json());
    if (auth.ok) {
        document.getElementById('login-section').style.display = 'none';
        document.getElementById('app-section').style.display = 'block';
        loadChannels();
    }
});

// 1. チャンネル一覧の初期読み込み
async function loadChannels() {
    const listContainer = document.getElementById('list-container');
    listContainer.innerHTML = '<p style="padding:20px; color:var(--sec);">チャンネル読み込み中...</p>';
    
    try {
        const res = await fetch('/api/all-channels');
        channels = await res.json();
        render();
    } catch (err) {
        listContainer.innerHTML = '<p style="padding:20px; color:var(--err);">読み込みに失敗しました。</p>';
    }
}

// 2. スライダー操作時のリアルタイム反映
document.getElementById('slider-months').oninput = (e) => {
    document.getElementById('val-months').textContent = e.target.value;
    render();
};

// 3. 並列分析ロジック（高速版）
async function analyze() {
    const targets = channels.filter(c => c.lastUploadDate === 'pending' && c.isSubscribed);
    if (targets.length === 0) return alert('分析が必要なチャンネルはありません。');
    
    document.getElementById('progress-area').style.display = 'block';
    const btnAnalyze = document.getElementById('btn-analyze');
    btnAnalyze.disabled = true;

    // チャンクに分けて並列実行
    for (let i = 0; i < targets.length; i += CONCURRENCY) {
        const chunk = targets.slice(i, i + CONCURRENCY);
        
        await Promise.all(chunk.map(async (c, index) => {
            try {
                const res = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({channelId: c.channelId})
                }).then(r => r.json());
                
                c.lastUploadDate = res.lastUploadDate;
            } catch (e) {
                c.lastUploadDate = 'none';
            }
            
            // 進捗表示の更新
            const currentCount = i + index + 1;
            const progress = Math.min((currentCount / targets.length) * 100, 100);
            document.getElementById('progress-text').textContent = `分析中 (${currentCount}/${targets.length})`;
            document.getElementById('progress-fill').style.width = `${progress}%`;
        }));
        
        render(); // 5件終わるごとにリストを更新
    }
    
    btnAnalyze.disabled = false;
    alert('全チャンネルの分析が完了しました。');
}

// 4. UI描画ロジック（フィルタリング・保護機能込）
function render() {
    const container = document.getElementById('list-container');
    const threshold = parseInt(document.getElementById('slider-months').value);
    container.innerHTML = '';
    
    let targetCount = 0;
    const now = new Date();

    channels.forEach(c => {
        if (!c.isSubscribed) return;

        let isOld = false;
        let infoText = '未分析';

        // 期間判定ロジック
        if (c.lastUploadDate !== 'pending' && c.lastUploadDate !== 'none') {
            const lastDate = new Date(c.lastUploadDate);
            const diffMonths = (now - lastDate) / (1000 * 60 * 60 * 24 * 30);
            isOld = diffMonths >= threshold;
            infoText = `最終投稿: ${c.lastUploadDate.split('T')[0]}`;
        } else if (c.lastUploadDate === 'none') {
            isOld = true;
            infoText = '投稿動画なし';
        }

        // 保護ロジック (ホワイトリスト or 登録者10万人以上)
        const isProtected = c.isFavorite || c.subscribers >= 100000;
        const shouldCheck = isOld && !isProtected;
        
        if (shouldCheck) targetCount++;

        const el = document.createElement('div');
        el.className = 'channel-item';
        el.innerHTML = `
            <input type="checkbox" class="cb" value="${c.subscriptionId}" 
                ${shouldCheck ? 'checked' : ''} ${isProtected ? 'disabled' : ''} 
                style="width:18px; height:18px; cursor:pointer;">
            <div class="fav-btn ${c.isFavorite ? 'active' : ''}" title="保護（お気に入り）">
                <i class="fa${c.isFavorite ? 's' : 'r'} fa-star"></i>
            </div>
            <img src="${c.thumbnails}">
            <div style="flex:1">
                <div style="font-weight:bold">${c.title} ${c.subscribers >= 100000 ? '<i class="fas fa-check-circle" style="color:var(--accent); font-size:0.8em;" title="有名チャンネル"></i>' : ''}</div>
                <div style="font-size:0.85em; color:var(--sec)">${infoText}</div>
            </div>
        `;

        // 星ボタンクリックイベント
        el.querySelector('.fav-btn').onclick = (e) => {
            e.stopPropagation();
            c.isFavorite = !c.isFavorite;
            render();
        };

        // マウスオーバーポップアップイベント
        el.onmouseenter = () => showPopup(c, infoText);
        el.onmousemove = (e) => movePopup(e);
        el.onmouseleave = () => hidePopup();

        container.appendChild(el);
    });

    // サマリー情報の更新
    document.getElementById('count-total').textContent = channels.length;
    document.getElementById('count-target').textContent = targetCount;
    document.getElementById('btn-delete').disabled = targetCount === 0;
}

// 5. ポップアップ制御関数
function showPopup(c, infoText) {
    const p = document.getElementById('channel-popup');
    document.getElementById('popup-img').src = c.thumbnails;
    document.getElementById('popup-title').textContent = c.title;
    document.getElementById('popup-info').innerHTML = `
        <i class="fas fa-users"></i> 登録者: ${c.subscribers.toLocaleString()}人<br>
        <i class="fas fa-video"></i> 動画数: ${c.videoCount}本<br>
        <i class="fas fa-clock"></i> 状況: ${infoText}
    `;
    p.style.display = 'block';
}

function movePopup(e) {
    const p = document.getElementById('channel-popup');
    p.style.left = (e.pageX + 15) + 'px';
    p.style.top = (e.pageY + 15) + 'px';
}

function hidePopup() {
    document.getElementById('channel-popup').style.display = 'none';
}

// 6. 一括解除実行
async function bulkDelete() {
    const ids = Array.from(document.querySelectorAll('.cb:checked')).map(cb => cb.value);
    if (!confirm(`${ids.length}件のチャンネル登録を解除します。よろしいですか？\n※保護されているチャンネルは含まれません。`)) return;

    const btn = document.getElementById('btn-delete');
    btn.disabled = true;
    btn.textContent = '解除処理中...';

    try {
        const res = await fetch('/api/subscriptions/bulk-delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({subscriptionIds: ids})
        }).then(r => r.json());

        alert(`完了: ${res.successCount}件成功 / ${res.failCount}件失敗`);
        
        // ローカルデータの更新（削除されたものをリストから除外）
        channels.forEach(c => {
            if (ids.includes(c.subscriptionId)) c.isSubscribed = false;
        });
        render();
    } catch (err) {
        alert('処理中にエラーが発生しました。');
    } finally {
        btn.textContent = '選択したチャンネルを解除';
    }
}

// イベントリスナーの登録
document.getElementById('btn-analyze').onclick = analyze;
document.getElementById('btn-delete').onclick = bulkDelete;
document.getElementById('btn-logout').onclick = () => { location.href = '/logout'; };
