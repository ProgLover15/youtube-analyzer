import os
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from flask import Flask, redirect, request, session, url_for, jsonify
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

# 環境変数の読み込み
load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')
app.secret_key = os.getenv("FLASK_SECRET_KEY")

if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY must be set in environment variables")

# HTTPS環境（Render等）でのセッション維持設定
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=3600
)

os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

def build_youtube_service():
    if 'credentials' not in session:
        return None
    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    return googleapiclient.discovery.build(API_SERVICE_NAME, API_VERSION, credentials=credentials)

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/login')
def login():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        {
            "web": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [os.getenv("REDIRECT_URI")]
            }
        },
        scopes=["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.readonly"]
    )
    flow.redirect_uri = os.getenv("REDIRECT_URI")
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    return redirect(auth_url)

@app.route('/callback')
def callback():
    flow = google_auth_oauthlib.flow.Flow.from_client_config(
        {
            "web": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [os.getenv("REDIRECT_URI")]
            }
        },
        scopes=["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.readonly"]
    )
    flow.redirect_uri = os.getenv("REDIRECT_URI")
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    return redirect(url_for('index'))

@app.route('/api/auth/status')
def auth_status():
    return jsonify({"ok": 'credentials' in session})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 1. チャンネル一覧取得（統計データ：登録者数・動画本数を含む）
@app.route('/api/all-channels')
def get_all_channels():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    
    all_subs = []
    try:
        next_page_token = None
        while True:
            # 登録チャンネル一覧の取得
            subs_res = youtube.subscriptions().list(
                part="snippet,contentDetails",
                mine=True,
                maxResults=50,
                pageToken=next_page_token
            ).execute()
            
            items = subs_res.get('items', [])
            if not items:
                break

            # 統計データ（登録者数等）を50件まとめて取得するためのIDリスト
            channel_ids = [item['snippet']['resourceId']['channelId'] for item in items]
            
            # channels().list で統計情報を一括取得
            stats_res = youtube.channels().list(
                part="statistics",
                id=",".join(channel_ids)
            ).execute()
            
            # IDをキーにした辞書を作成
            stats_map = {s['id']: s['statistics'] for s in stats_res.get('items', [])}

            for item in items:
                c_id = item['snippet']['resourceId']['channelId']
                stats = stats_map.get(c_id, {})
                
                all_subs.append({
                    "subscriptionId": item['id'],
                    "channelId": c_id,
                    "title": item['snippet']['title'],
                    "thumbnails": item['snippet']['thumbnails']['default']['url'],
                    "lastUploadDate": "pending", # フロントエンドの分析待ち
                    "isSubscribed": True,
                    "isFavorite": False,
                    "subscribers": int(stats.get('subscriberCount', 0)),
                    "videoCount": int(stats.get('videoCount', 0))
                })
            
            next_page_token = subs_res.get('nextPageToken')
            if not next_page_token:
                break
                
        return jsonify(all_subs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 2. 個別チャンネルの最終投稿日分析
@app.route('/api/analyze', methods=['POST'])
def analyze():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
        
    data = request.get_json()
    channel_id = data.get('channelId')
    
    try:
        # アップロードプレイリストIDの取得
        c_res = youtube.channels().list(part="contentDetails", id=channel_id).execute()
        if not c_res.get("items"):
            return jsonify({"lastUploadDate": "none"})
            
        uploads_id = c_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        
        # 最新の動画1件を取得
        p_res = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_id,
            maxResults=1
        ).execute()
        
        date = "none"
        if p_res.get("items"):
            date = p_res["items"][0]["snippet"]["publishedAt"]
        
        return jsonify({"channelId": channel_id, "lastUploadDate": date})
    except Exception:
        return jsonify({"lastUploadDate": "none"})

# 3. 登録解除（一括対応）
@app.route('/api/subscriptions/bulk-delete', methods=['POST'])
def bulk_delete():
    youtube = build_youtube_service()
    if not youtube:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.get_json()
    ids = data.get('subscriptionIds', [])
    success_count = 0
    fail_count = 0
    
    for s_id in ids:
        try:
            youtube.subscriptions().delete(id=s_id).execute()
            success_count += 1
        except Exception:
            fail_count += 1
            
    return jsonify({
        "successCount": success_count,
        "failCount": fail_count
    })

if __name__ == '__main__':
    app.run(debug=True)
